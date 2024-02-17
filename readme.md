# SDMTR: A Brain-inspired Transformer for Relation Inference

This repository contains the code to reproduce the `relational reasoning: sort_of_clever`,text-based question-answering: bAbI and `detecting equilateral triangles` tasks from our paper.  


## Install relevant libraries
```
pip install -r requirements.txt 
```
## Task1: Sort-of-CLEVR
You can find the source code for the Sort-of-CLEVR task in `sort_of_clevr_and_babi` folder.

Firstly, dataset generation:
```
python sort_of_clevr_generator.py
```
**Then, you can run `sort_main.py` directly.**

**Or execute the following commands to reproduce the experimental results of the Sort-of-CLEVR dataset in our paper.**
```
sh sdmtr_sort.sh h_dim num_layers share_vanilla_parameters use_topk topk shared_memory_attention mem_slots use_long_men long_mem_segs long_mem_aggre seed set_transformer
```
**Description of parameter meaning:**

`h_dim`: Embedding dimensions

`num_layers`: Number of model layers

`share_vanilla_parameters`: Whether share parameters across layers. If False, it will run TR + HC. For shared workspace and long-term memory experiments it should be True.

`use_topk`: Whether to use top-k competition

`topk`: Value of k in top-k competition

`shared_memory_attention`: Whether to use shared workspace and long-term memory

`mem_slots`: Number of slots in workspace

`use_long_men`: Whether to use long-term memory component. It must be True in our SDMTR.

`long_mem_segs`: Number of long-term memory segments

`long_mem_aggre`: Whether cross-attention is performed on information retrieved from the workspace and long-term memory. If True, it will run SDMTR_NL.

`seed`: Random seed

`functional`: ues Set Transformer (ISAB) or not. If True, it will run ISAB.

**Specifically, please execute the following commands to reproduce all experiments for the Sort-of-CLEVR task in the paper:**

```
SDMTR
sh sdmtr_sort.sh 256 4 True True 5 True 8 True 5 False 1 False

SDMTR_NS (SDMTR_w/o1)
sh sdmtr_sort.sh 256 4 False True 5 True 8 True 5 False 1 False

SDMTR_NL (SDMTR_w/o2)
sh sdmtr_sort.sh 256 4 True True 5 True 8 True 5 True 1 False

SDMTR+S
sh sdmtr_sort.sh 256 4 True False 5 True 8 True 5 False 1 False

TR + HSW
sh sdmtr_sort.sh 256 4 True True 5 True 8 False 5 False 1 False

TR
sh sdmtr_sort.sh 256 4 True False 5 False 8 False 5 False 1 False

TR + HC
sh sdmtr_sort.sh 256 4 False False 5 False 8 False 5 False 1 False

ISAB
sh sdmtr_sort.sh 256 4 False False 5 False 8 False 5 False 1 True

```
[comment]: <> (**Results**)

[comment]: <> (![sort一元结果]&#40;./sort_of_clevr_and_babi/result_pic/Unary_Accuracy.png&#41;)

[comment]: <> (![sort二元结果]&#40;./sort_of_clevr_and_babi/result_pic/Binary_Accuracy.png&#41;)

[comment]: <> (![sort三元结果]&#40;./sort_of_clevr_and_babi/result_pic/Ternary_Accuracy.png&#41;)

## Task2: bAbI
You can find the source code for the bAbI task in `sort_of_clevr_and_babi` folder.

**Specifically, please run `babi_main.py` directly.**

**Or execute the following commands to reproduce all experiments for the bAbI task in the paper:**

```
SDMTR
sh sdmtr_babi.sh 256 4 True True 5 True 8 True 5 False 1 False

SDMTR_NS (SDMTR_w/o1)
sh sdmtr_babi.sh 256 4 False True 5 True 8 True 5 False 1 False

SDMTR_NL (SDMTR_w/o2)
sh sdmtr_babi.sh 256 4 True True 5 True 8 True 5 True 1 False

SDMTR+S
sh sdmtr_babi.sh 256 4 True False 5 True 8 True 5 False 1 False

TR + HSW
sh sdmtr_babi.sh 256 4 True True 5 True 8 False 5 False 1 False
```

## Task3: Detecting Equilateral Triangles 
You can find the source code for the Triangle task in `Triangle` folder.

**Specifically, please run `run.py` directly.**

**Or execute the following commands to reproduce all experiments for the Triangle task in the paper:**

```
sh run.sh dataset model patch_size num_layers h_dim ffn_dim share_vanilla_parameters use_topk topk shared_memory_attention mem_slots use_long_men long_mem_segs long_mem_aggre seed
```

```
SDMTR
sh run_T.sh "Triangle" "default" 32 2 128 256 True True 5 True 8 True 5 False 1

SDMTR_NS (SDMTR_w/o1)
sh run.sh "Triangle" "default" 32 2 128 256 True True 5 True 8 False 5 False 1

SDMTR_NL (SDMTR_w/o2)
sh run.sh "Triangle" "default" 32 2 128 256 True True 5 True 8 False 5 True 1

SDMTR+S
sh run.sh "Triangle" "default" 32 2 128 256 True False 5 True 8 True 5 False 1

TR + HSW
sh run.sh "Triangle" "default" 4 4 128 256 True True 5 True 8 False 5 False 1

TR
sh run.sh "Triangle" "default" 4 4 128 256 True False 5 False 8 False 5 False 1

STR
sh run.sh "Triangle" "default" 4 4 128 256 True True 5 False 8 False 5 False 1

TR + HC
sh run.sh "Triangle" "default" 4 4 128 256 False False 5 False 8 False 5 False 1

ISAB
sh run.sh "Triangle" "functional" 4 4 128 256 False False 5 False 8 False 5 False 1
```