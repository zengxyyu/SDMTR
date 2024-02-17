import numpy as np
import os
import torch
import torch.nn.functional as F
from torch import nn
from .pos_enc import PositionEncoder
from .GroupLinearLayer import GroupLinearLayer
# os.environ["CUDA_VISIBLE_DEVICES"] = "1"  # 将1替换为要使用的GPU索引
device = torch.device("cuda:4" if torch.cuda.is_available() else "cpu")


# this class largely follows the official sonnet implementation
# https://github.com/deepmind/sonnet/blob/master/sonnet/python/modules/relational_memory.py

class RepeatLinear(nn.Module):
    '''
    RepeatLinear 模块的作用是将输入 x 映射为一个输出 y，其中会对输入进行一定的特征提取和变换。
   in_dim, out_dim, num_steps: 256 512 20
    '''

    def __init__(self, in_dim, out_dim, num_steps):
        super().__init__()
        # 1.
        self.pe = PositionEncoder(in_dim)
        self.num_steps = num_steps
        # self.w = nn.Parameter(torch.randn(in_dim).cuda())
        self.w = nn.Parameter(torch.randn(in_dim))
        # 2.
        self.linear = nn.Linear(in_dim, out_dim)

    def forward(self, x):
        w = self.w.unsqueeze(0).repeat(self.num_steps, 1)
        w = self.w.unsqueeze(0).repeat(x.size(0), 1, 1)
        # w = self.pe(w)

        x = torch.relu(w * x)

        x = torch.mean(x, dim=1)

        x = self.linear(x)

        return x


def count_parameters(name, model):
    '''
    计算模型中参数（包括权重和偏置项）的总数量
    '''
    k = 0
    for p in model.parameters():
        k += p.numel()  # 一个形状为(3, 4, 5)的张量, p.numel()将返回60

    # print(name, end = ':')
    # print(k)
    print("{} 的参数量为: {}".format(name, k))


class RelationalMemory(nn.Module):
    """
    Constructs a `RelationalMemory` object.
    This class is same as the RMC from relational_rnn_models.py, but without language modeling-specific variables.
    Args:
      mem_slots: The total number of memory slots to use.
      head_size: The size of an attention head.
      input_size: The size of input per step. i.e. the dimension of each input vector
      num_heads: The number of attention heads to use. Defaults to 1.
      num_blocks: Number of times to compute attention per time step. Defaults to 1. ???
      forget_bias: Bias to use for the forget gate, assuming we are using
        some form of gating. Defaults to 1.
      input_bias: Bias to use for the input gate, assuming we are using
        some form of gating. Defaults to 0.
      gate_style: Whether to use per-element gating ('unit'),
        per-memory slot gating ('memory'), or no gating at all (None).
        Defaults to `unit`.
      attention_mlp_layers: Number of layers to use in the post-attention MLP. Defaults to 2.
      key_size: Size of vector to use for key & query vectors in the attention
        computation. Defaults to None, in which case we use `head_size`.
      name: Name of the module.

      # NEW flag for this class
      return_all_outputs: Whether the model returns outputs for each step (like seq2seq) or only the final output.
    Raises:
      ValueError: gate_style not one of [None, 'memory', 'unit'].
      ValueError: num_blocks is < 1.
      ValueError: attention_mlp_layers is < 1.
    """

    def __init__(self, mem_slots, head_size, input_size, output_size, num_heads=1, num_blocks=1, forget_bias=1.,
                 input_bias=0.,
                 gate_style='unit', attention_mlp_layers=2, key_size=None, return_all_outputs=False, use_topk=False,
                 topk=3, num_steps=5,
                 null_attention=False):
        super(RelationalMemory, self).__init__()

        ########## generic parameters for RMC ##########
        self.mem_slots = mem_slots
        self.head_size = head_size
        self.num_heads = num_heads
        # 记忆大小 = 头大小*头数目(一行的数目)
        self.mem_size = self.head_size * self.num_heads
        self.use_topk = use_topk
        self.topk = topk

        # a new fixed params needed for pytorch port of RMC
        # +1 is the concatenated input per time step : we do self-attention with the concatenated memory & input
        # so if the mem_slots = 1, this value is 2
        self.mem_slots_plus_input = self.mem_slots + 1

        if num_blocks < 1:
            raise ValueError('num_blocks must be >=1. Got: {}.'.format(num_blocks))
        self.num_blocks = num_blocks

        print("Using gate style", gate_style)
        if gate_style not in ['unit', 'memory', None]:
            raise ValueError(
                'gate_style must be one of [\'unit\', \'memory\', None]. got: '
                '{}.'.format(gate_style))
        self.gate_style = gate_style

        if attention_mlp_layers < 1:
            raise ValueError('attention_mlp_layers must be >= 1. Got: {}.'.format(
                attention_mlp_layers))
        self.attention_mlp_layers = attention_mlp_layers

        self.key_size = key_size if key_size else self.head_size
        self.attn_log = None

        ########## parameters for multihead attention ##########
        # value_size is same as head_size 64
        self.value_size = self.head_size
        # total size for query-key-value  32*2+64=128
        self.qkv_size = 2 * self.key_size + self.value_size
        self.total_qkv_size = self.qkv_size * self.num_heads  # denoted as F

        # 1.2.1 计算query_proj、key_proj、value_proj
        self.query_proj = nn.Linear(self.mem_size, self.key_size * self.num_heads)
        print("self.key_size的大小为: {},self.num_heads大小为: {}".format(self.key_size, self.num_heads))
        count_parameters("query", self.query_proj)
        self.key_proj = nn.Linear(self.mem_size, self.key_size * self.num_heads)
        count_parameters("key", self.key_proj)
        self.value_proj = nn.Linear(self.mem_size, self.value_size * self.num_heads)
        print("self.value_size: {},self.num_heads大小为: {}".format(self.value_size, self.num_heads))
        count_parameters("value", self.value_proj)

        # each head has qkv_sized linear projector
        # just using one big param is more efficient, rather than this line
        # self.qkv_projector = [nn.Parameter(torch.randn((self.qkv_size, self.qkv_size))) for _ in range(self.num_heads)]
        # self.qkv_projector = nn.Linear(self.mem_size, self.total_qkv_size)
        # self.qkv_layernorm = nn.LayerNorm(self.total_qkv_size)

        # used for attend_over_memory function
        # 1.2.2 四个Linear
        self.attention_mlp = nn.ModuleList([nn.Linear(self.mem_size, self.mem_size)] * self.attention_mlp_layers)
        count_parameters("attention_mlp", self.attention_mlp[0])
        # 1.2.3两次归一化操作
        self.attended_memory_layernorm = nn.LayerNorm(self.mem_size)
        count_parameters("layernorm1", self.attended_memory_layernorm)
        self.attended_memory_layernorm2 = nn.LayerNorm(self.mem_size)
        count_parameters("layernorm2", self.attended_memory_layernorm2)
        self.attended_memory_layernorm3 = nn.LayerNorm(self.mem_size)

        ########## parameters for initial embedded input projection ##########
        # 1.2.4
        self.input_size = input_size  # 256
        # 对初始输入进行投影，以便与记忆进行拼接，从而计算关系注意力  self.mem_size为256
        self.input_projector = nn.Linear(self.input_size, self.mem_size)
        count_parameters("input_projector", self.input_projector)
        print('input_projector与mem_size维度一样为:' + str(self.mem_size))

        # self.output_projector = nn.Linear(self.output_size, self.input_size)

        ########## parameters for gating ##########
        self.num_gates = 2 * self.calculate_gate_size()
        print("门控类型: {},门控的总数目为: 2*{}".format(gate_style, self.calculate_gate_size()))

        if gate_style in ['unit', 'memory']:
            # RepeatLinear中有对输入的位置编码
            # 输入门
            self.input_gate_projector = RepeatLinear(self.mem_size, self.num_gates, num_steps)
            count_parameters("input_gate_projector", self.input_gate_projector)

            # 记忆门
            self.memory_gate_projector = GroupLinearLayer(self.mem_size, self.num_gates, self.mem_slots)
            # self.memory_gate_projector = nn.Linear(self.mem_size, self.num_gates)
            count_parameters("memory_gate_projector", self.memory_gate_projector)

        # trainable scalar gate bias tensors
        self.forget_bias = nn.Parameter(torch.tensor(forget_bias, dtype=torch.float32))
        self.input_bias = nn.Parameter(torch.tensor(input_bias, dtype=torch.float32))

        ########## number of outputs returned #####
        # Whether the model returns outputs for each step (like seq2seq) or only the final output.
        self.return_all_outputs = return_all_outputs

        self.null_attention = null_attention

        print("relational volatie!!!")
        # self.competition_mlp = nn.Sequential(nn.Linear(self.mem_slots * self.mem_size + self.mem_size, 256),
        #                            nn.ReLU(),
        #                            nn.Linear(256, 256),
        #                            nn.ReLU(),
        #                            nn.Linear(256, 256),
        #                            nn.ReLU(),
        #                            nn.Linear(256, 2))

    def repackage_hidden(self, h):
        """Wraps hidden states in new Tensors, to detach them from their history."""
        # needed for truncated BPTT, called at every batch forward pass
        if isinstance(h, torch.Tensor):
            return h.detach()
        else:
            return tuple(self.repackage_hidden(v) for v in h)

    def initial_state(self, batch_size, trainable=False):
        """
        Creates the initial memory. 创建初始内存
        We should ensure each row of the memory is initialized to be unique,
        so initialize the matrix to be the identity. We then pad or truncate 填充或者压缩
        as necessary so that init_state is of size
        (batch_size, self.mem_slots, self.mem_size).
        Args:
          batch_size: The size of the batch.
          trainable: Whether the initial state is trainable. This is always True.
        Returns:
          init_state: A truncated or padded matrix of size 初始化状态
            (batch_size, self.mem_slots, self.mem_size).
        """
        if True:
            init_Mr = torch.stack(
                [torch.rand(5, self.mem_slots, self.mem_size) for _ in range(batch_size)])
            init_state = torch.stack([torch.eye(self.mem_slots) for _ in range(batch_size)])
            # pad the matrix with zeros 用0填充矩阵
            if self.mem_size > self.mem_slots:
                difference = self.mem_size - self.mem_slots
                pad = torch.zeros((batch_size, self.mem_slots, difference))
                init_state = torch.cat([init_state, pad], -1)

            # truncation. take the first 'self.mem_size' components
            elif self.mem_size < self.mem_slots:
                init_state = init_state[:, :, :self.mem_size]

            return init_state, init_Mr
        else:
            init_state = torch.randn(batch_size, self.mem_slots, self.mem_size)
            return init_state

    def multihead_attention(self, input, memory, use_topk_=True, store_log=True):
        """
        Perform multi-head attention from 'Attention is All You Need'.
        Implementation of the attention mechanism from
        https://arxiv.org/abs/1706.03762.
        Args:
          memory: Memory tensor to perform attention on. 用于集中注意力的记忆张量
        Returns:
          new_memory: New memory tensor.  返回新的张量
        """
        # 1.RMC的A部分用此函数生成新记忆, q为记忆M k,v应该为为R矩阵[M:A]
        # 2.广播过程 memory=input_reshape input=new_memory 用此产生新hx
        q = self.query_proj(memory)
        k = self.key_proj(input)
        v = self.value_proj(input)

        q = q.reshape(q.size(0), q.size(1), self.num_heads, -1).permute(0, 2, 1, 3)  # 2.(64,4,27,32)
        k = k.reshape(k.size(0), k.size(1), self.num_heads, -1).permute(0, 2, 1, 3)  # 2.(64,4,8,32)
        v = v.reshape(v.size(0), v.size(1), self.num_heads, -1).permute(0, 2, 1, 3)  # 2.(64,4,8,64)
        scores = torch.matmul(q, k.transpose(2, 3))  # 1.(64,4,8,27) 2.(64,4,27,8)

        scores = torch.softmax(scores, dim=-1)

        # scores_save = scores.cpu().numpy()
        # np.save('attention_scores_bf_top-k', scores_save)
        # print("q and k scores before top-k:", scores)
        # if store_log:
        #    self.attn_log = scores[0]
        if not self.null_attention:
            # self.null_attention 为 false
            if self.use_topk and use_topk_:  # 对scores进行top-k筛选  TR+HSW在更新记忆RMC的A部分时会进入
                # 使scores中top-k个位置为1，其余位置为0。当属于更新记忆时,实现竞争写入,选取topk
                if self.topk < scores.size()[-1]:
                    topk = torch.topk(scores, dim=-1, k=self.topk)
                    mask = torch.zeros(scores.size()).to(scores.device)
                    mask.scatter_(3, topk.indices, 1)
                    scores = scores * mask
                else:
                    scores = scores
        else:
            memory_flat = memory.reshape(memory.size(0), -1).unsqueeze(1)
            memory_flat = memory_flat.repeat(1, input.shape[1], 1)
            # 将输入与拉平的记忆cat
            N = torch.cat((input, memory_flat), dim=2)
            N = self.competition_mlp(N)
            N = torch.nn.functional.gumbel_softmax(N, dim=2, hard=True, tau=0.5)
            N = N[:, :, 0]
            scores = scores * N.unsqueeze(1).unsqueeze(1)
        # 1.RMC的A部分 scores=(64,4,8,27)  v=(64,4,27,64) output=(64,4,8,64)  8*27*27*64
        # 2.广播过程 scores=(64,4,27,8)   v=(64,4,8,64)  output=(64,4,27,64)
        # print("q and k scores after top-k:", scores)
        # scores_save_af = scores.cpu().numpy()
        # np.save('attention_scores_after_top-k', scores_save_af)
        output = torch.matmul(scores, v)

        """#print(memory.size())
        # First, a simple linear projection is used to construct queries
        qkv = self.qkv_projector(memory)
        # apply layernorm for every dim except the batch dim
        qkv = self.qkv_layernorm(qkv)

        # mem_slots needs to be dynamically computed since mem_slots got concatenated with inputs
        # example: self.mem_slots=10 and seq_length is 3, and then mem_slots is 10 + 1 = 11 for each 3 step forward pass
        # this is the same as self.mem_slots_plus_input, but defined to keep the sonnet implementation SDMTR style
        mem_slots = memory.shape[1]  # denoted as N

        # split the qkv to multiple heads H
        # [B, N, F] => [B, N, H, F/H]
        qkv_reshape = qkv.view(qkv.shape[0], mem_slots, self.num_heads, self.qkv_size)

        # [B, N, H, F/H] => [B, H, N, F/H]
        qkv_transpose = qkv_reshape.permute(0, 2, 1, 3)

        # [B, H, N, key_size], [B, H, N, key_size], [B, H, N, value_size]
        q, k, v = torch.split(qkv_transpose, [self.key_size, self.key_size, self.value_size], -1)

        # scale q with d_k, the dimensionality of the key vectors
        q *= (self.key_size ** -0.5)

        # make it [B, H, N, N]
        dot_product = torch.matmul(q, k.permute(0, 1, 3, 2))
        weights = F.softmax(dot_product, dim=-1)

        if self.use_topk:
            topk = torch.topk(weights, dim = -1, k = self.topk)
            mask = torch.zeros(weights.size()).to(weights.device)
            mask.scatter_(3, topk.indices, 1)
            weights = weights * mask

        # output is [B, H, N, V]
        output = torch.matmul(weights, v)"""

        # [B, H, N, V] => [B, N, H, V] => [B, N, H*V]
        output_transpose = output.permute(0, 2, 1, 3).contiguous()
        new_memory = output_transpose.view((output_transpose.shape[0], output_transpose.shape[1], -1))  # (64,8,256)
        return new_memory

    @property
    def state_size(self):
        return [self.mem_slots, self.mem_size]

    @property
    def output_size(self):
        return self.mem_slots * self.mem_size

    def print_log(self):
        print(self.attn_log)

    def calculate_gate_size(self):
        """
        Calculate the gate size from the gate_style.
        Returns:
          The per sample, per head parameter size of each gate.
        """
        if self.gate_style == 'unit':
            return self.mem_size
        elif self.gate_style == 'memory':
            return 1
        else:  # self.gate_style == None
            return 0

    def create_gates(self, inputs, memory):
        """
        Create input and forget gates for this step using `inputs` and `memory`.
        Args:
          inputs: Tensor input.
          memory: The current state of memory.
        Returns:
          input_gate: A LSTM-like insert gate.
          forget_gate: A LSTM-like forget gate.
        """
        # We'll create the input and forget gates at once. Hence, calculate double
        # the gate size.

        # equation 8: since there is no output gate, h is just a tanh'ed m  隐藏层h的计算，省去了输出门
        memory = torch.tanh(memory)

        # TODO: check this input flattening is correct
        # sonnet uses this, but i think it assumes time step of 1 for all cases
        # if inputs is (B, T, features) where T > 1, this gets incorrect
        # inputs = inputs.view(inputs.shape[0], -1)

        # fixed implementation
        if len(inputs.shape) == 3:
            # if inputs.shape[1] > 1:
            #    raise ValueError(
            #        "input seq length is larger than 1. create_gate function is meant to be called for each step, with input seq length of 1")

            # matmul for equation 4 and 5
            # there is no output gate, so equation 6 is not implemented
            # print('jello')
            gate_inputs = self.input_gate_projector(inputs)
            gate_inputs = gate_inputs.unsqueeze(dim=1)
            gate_memory = self.memory_gate_projector(memory)
        else:
            raise ValueError("input shape of create_gate function is 2, expects 3")

        # this completes the equation 4 and 5
        # print(gate_inputs.size())
        # print(gate_memory.size())
        gates = gate_memory + gate_inputs
        # self.attn_log = gates[0]
        gates = torch.split(gates, split_size_or_sections=int(gates.shape[2] / 2), dim=2)
        input_gate, forget_gate = gates
        assert input_gate.shape[2] == forget_gate.shape[2]

        # to be used for equation 7
        self.attn_log = torch.zeros(input_gate.shape[1], input_gate.shape[2], 2)
        self.attn_log[:, :, 0] = input_gate[0].cpu()

        input_gate = torch.sigmoid(input_gate + self.input_bias)
        forget_gate = torch.sigmoid(forget_gate + self.forget_bias)

        return input_gate, forget_gate

    def attend_over_memory(self, inputs, memory):
        """
        Perform multiheaded attention over `memory`.
            Args:
              memory: Current relational memory.
              inputs: Current inputs.
            Returns:
              The attended-over memory.
        """
        for _ in range(self.num_blocks):
            # RMC的A部分  (B64,num_slots8,D256)
            attended_memory = self.multihead_attention(inputs, memory)
            # Add a skip connection to the multiheaded attention's input.   残差连接+LayerNorm操作
            memory = self.attended_memory_layernorm(memory + attended_memory)

            # add a skip connection to the attention_mlp's input.
            attention_mlp = memory
            for i, l in enumerate(self.attention_mlp):
                attention_mlp = self.attention_mlp[i](attention_mlp)
                attention_mlp = F.relu(attention_mlp)
            memory = self.attended_memory_layernorm2(memory + attention_mlp)

            # # 更新Mr
            # Mr0 = torch.einsum('bmnd,bnf->bmnf', Mr, memory)
            # # Mr += Mr0
            # Mr = self.attended_memory_layernorm3(Mr + Mr0)

            # Mr_step = Mr.permute(1, 0, 2, 3)  # new_Mr(MBND)
            # x = []
            # for i in range(Mr_step.shape[0]):
            #     Mr_attend = self.multihead_attention(memory, Mr_step[i])  # (B,N,D)
            #     x.append(Mr_attend)
            # Mr_attend = torch.stack(x).permute(1, 0, 2, 3)  # 得到的Mr_attend(B,M,N,D)
            # Mr += Mr_attend

            # memory = self.multihead_attention(memory, memory, use_topk_ = False, store_log = False)
            # Mr[0] = memory

        return memory

    def forward_step(self, inputs, memory, Mr, treat_input_as_matrix=False):
        """
        Forward step of the relational memory core.
        Args:
          inputs: Tensor input.
          memory: Memory output from the previous time step.
          treat_input_as_matrix: Optional, whether to treat `input` as a sequence
            of matrices. Default to False, in which case the input is flattened
            into a vector.
        Returns:
          output: This time step's output.
          next_memory: The next version of memory to use.
        """

        if treat_input_as_matrix:
            # keep (Batch, Seq, ...) dim (0, 1), flatten starting from dim 2
            inputs = inputs.view(inputs.shape[0], inputs.shape[1], -1)
            # apply linear layer for dim 2   将输入变为与记忆一样的dim，方便计算
            inputs_reshape = self.input_projector(inputs)
        else:
            # keep (Batch, ...) dim (0), flatten starting from dim 1
            inputs = inputs.view(inputs.shape[0], -1)
            # apply linear layer for dim 1
            inputs = self.input_projector(inputs)
            # unsqueeze the time step to dim 1
            inputs_reshape = inputs.unsqueeze(dim=1)

        # 第三步.开始进入整个RMC图更新记忆
        # memory_plus_input = torch.cat([memory, inputs_reshape], dim=1)
        # print(memory_plus_input.size())  inputs_reshape = (64,27,256)  memory = (64,8,256)
        next_memory = self.attend_over_memory(inputs_reshape, memory)  # new_Mr(BMND)
        # 更新Mr
        Mr_op = torch.einsum('bmnd,bnf->bmnf', Mr, next_memory)
        Mr_new = self.attended_memory_layernorm3(Mr + Mr_op)
        # # 更新Mr
        # Mr_op = torch.einsum('bmnd,bnf->bmnf', Mr, next_memory)
        # # Mr += Mr0
        # Mr_new = self.attended_memory_layernorm3(Mr + Mr_op)

        # cut out the concatenated input vectors from the original memory slots
        # n = inputs_reshape.shape[1]
        # next_memory = next_memory[:, :-n, :]
        if self.gate_style == 'unit' or self.gate_style == 'memory':  # 使用门控机制
            # these gates are sigmoid-applied ones for equation 7
            input_gate, forget_gate = self.create_gates(inputs_reshape, memory)
            # equation 7 calculation
            next_memory = input_gate * torch.tanh(next_memory)
            next_memory += forget_gate * memory
            self.attn_log[:, :, 1] = input_gate[0].cpu()

        output = next_memory.reshape(next_memory.shape[0], -1)  # (64,2048)
        # 第四步.广播过程  用新的memory更新hx  inputs_reshape为q next_memory为k,v
        hx1 = self.multihead_attention(next_memory, inputs_reshape, use_topk_=False, store_log=False)

        # Mr_step = new_Mr.permute(1,0,2,3)   # new_Mr(MBND)
        # x = []
        # for i in range(Mr_step.shape[0]):
        #     Mr0 = self.multihead_attention(Mr_step[i], next_memory, use_topk_=False, store_log=False)
        #     x.append(Mr0)
        # Mr0 = torch.stack(x).permute(1,0,2,3)  # 得到的hx(M,B,N,D)
        # new_Mr += Mr0
        # hx = torch.mean(hx, dim=0)
        # way1
        # Mr_step = new_Mr.permute(1,0,2,3)   # Mr_step(MBND)
        # x = []
        # for i in range(Mr_step.shape[0]):
        #     Mr0 = self.multihead_attention(Mr_step[i], inputs_reshape, use_topk_=False, store_log=False)
        #     x.append(Mr0)
        # hx = torch.stack(x) # 得到的hx(M,B,N,D)
        # hx = torch.mean(hx, dim=0)
        # hx = (hx + hx1)/2
        # return output, next_memory, new_Mr, hx
        # way2
        # Mr_step = new_Mr.permute(1, 0, 2, 3)  # Mr_step(MBND)
        Mr_step = torch.mean(Mr_new, dim=1)  # Mr_step(BND)
        # if self.gate_style == 'unit' or self.gate_style == 'memory':  # 使用门控机制
        #     # these gates are sigmoid-applied ones for equation 7
        #     input_gate_Mr, forget_gate_Mr = self.create_gates(inputs_reshape, Mr_step)
        #     next_Mr_step = input_gate_Mr * torch.tanh(Mr_step)
        #     next_Mr_step += forget_gate_Mr * torch.mean(Mr, dim=1)
        #     self.attn_log[:, :, 1] = input_gate_Mr[0].cpu()
        hx2 = self.multihead_attention(Mr_step, inputs_reshape)
        hx2 = self.multihead_attention(hx1, hx2, use_topk_=False, store_log=False)
        hx = hx1*0.7 + hx2*0.3
        return output, next_memory, Mr_new, hx


    def forward(self, inputs, memory, Mr, parallel=True):
        # Starting each batch, we detach the hidden state from how it was previously produced.
        # If we didn't, the model would try backpropagating all the way to start of the dataset.
        # memory = self.repackage_hidden(memory)

        # for loop implementation of (entire) recurrent forward pass of the model
        # inputs is batch first [batch, seq], and output logit per step is [batch, vocab]
        # so the concatenated logits are [seq * batch, vocab]

        # targets are flattened [seq, batch] => [seq * batch], so the dimension is correct
        logits = []
        # print("relational_memory_volatile.py中前向传播的inputs大小为：", inputs.size())
        # print("relational_memory_volatile.py中前向传播的memory大小为：", memory.size())
        # memory = self.repackage_hidden(memory)
        # shape[1] is seq_lenth T
        if not parallel:
            # parallel = false
            for idx_step in range(inputs.shape[1]):
                logit, memory = self.forward_step(inputs[:, idx_step].to(device), memory.to(device))
                logits.append(logit)
            logits = torch.cat(logits)
        else:
            # logits = (64,2048)  TR+HSW way
            logits, memory, Mr, hx = self.forward_step(inputs.to(device), memory.to(device), Mr.to(device),
                                                       treat_input_as_matrix=True)

        memory_out = None  # self.output_projector(memory.view(memory.shape[0], -1))
        if self.return_all_outputs:
            return logits, memory_out, memory, Mr, hx
        else:
            return logits, memory_out, memory, Mr, hx

# ########## DEBUG: unit test SDMTR ##########
# input_size = 44
# seq_length = 1
# batch_size = 32
# model = RelationalMemory(mem_slots=10, head_size=20, input_size=input_size, num_tokens=66, num_heads=8, num_blocks=1, forget_bias=1., input_bias=0.)
# model_memory = model.initial_state(batch_size=batch_size)
#
# # random input
# random_input = torch.randn((32, seq_length, input_size))
# # random targets
# random_targets = torch.randn((32, seq_length, input_size))
#
# # take a one step forward
# logit, next_memory = model(random_input, model_memory, random_targets, treat_input_as_matrix=True)
