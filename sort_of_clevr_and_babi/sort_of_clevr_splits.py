import cv2
import os
import numpy as np
import random
import pickle
import argparse

parser = argparse.ArgumentParser(description='Generate Sort-of-ClEVR (https://arxiv.org/abs/1706.01427)')
parser.add_argument('--train_size', type=int, default=9800) #9800
parser.add_argument('--test_size', type=int, default=200) #200
parser.add_argument('--image_size', type=int, default=75) #75
parser.add_argument('--object_size', type=int, default=5)
parser.add_argument('--nb_questions', type=int, default=10) # 10 relational and 10 non-rel qst per image
parser.add_argument('--nb_heldout_colors', type=int, default=0)

args = parser.parse_args()

train_size = args.train_size
test_size = args.test_size
img_size = args.image_size
size = args.object_size
nb_questions = args.nb_questions

question_size = 11 # 6 for one-hot vector of color, 2 for question type, 3 for question subtype
dirs = './data'

all_colors = [
    (0,0,255),##r
    (0,255,0),##g
    (255,0,0),##b
    (0,156,255),##o
    (128,128,128),##k
    (0,255,255)##y
]

try:
    os.makedirs(dirs)
except:
    print('directory {} already exists'.format(dirs))

def center_generate(objects):
    while True:
        pas = True
        center = np.random.randint(0+size, img_size - size, 2)        
        if len(objects) > 0:
            for name,c,shape in objects:
                if ((center - c) ** 2).sum() < ((size * 2) ** 2):
                    pas = False
        if pas:
            return center

def build_dataset(left_out_color=0):
    objects = []
    img = np.ones((img_size,img_size,3)) * 255

    colors = all_colors[left_out_color:]

    for color_id,color in enumerate(colors):  
        center = center_generate(objects)
        if random.random()<0.5: # 2 possible shapes
            start = (center[0]-size, center[1]-size)
            end = (center[0]+size, center[1]+size)
            cv2.rectangle(img, start, end, color, -1)
            objects.append((color_id,center,'r'))
        else:
            center_ = (center[0], center[1])
            cv2.circle(img, center_, size, color, -1)
            objects.append((color_id,center,'c'))


    rel_questions = []
    norel_questions = []
    rel_answers = []
    norel_answers = []

    """Non-relational questions"""
    for _ in range(nb_questions):
        question = np.zeros((question_size))
        color = random.randint(0,len(colors) - 1)
        question[color] = 1
        question[6] = 1
        subtype = random.randint(0,2)
        question[subtype+8] = 1
        norel_questions.append(question)
        """Answer : [yes, no, rectangle, circle, r, g, b, o, k, y]"""
        if subtype == 0:
            """query shape->rectangle/circle"""
            if objects[color][2] == 'r':
                answer = 2
            else:
                answer = 3

        elif subtype == 1:
            """query horizontal position->yes/no"""
            if objects[color][1][0] < img_size / 2:
                answer = 0
            else:
                answer = 1

        elif subtype == 2:
            """query vertical position->yes/no"""
            if objects[color][1][1] < img_size / 2:
                answer = 0
            else:
                answer = 1
        norel_answers.append(answer)
    
    """Relational questions"""
    for i in range(nb_questions):
        question = np.zeros((question_size))
        color = random.randint(0,len(colors) - 1)
        question[color] = 1
        question[7] = 1
        subtype = random.randint(0,2)
        question[subtype+8] = 1
        rel_questions.append(question)

        if subtype == 0:
            """closest-to->rectangle/circle"""
            my_obj = objects[color][1]
            dist_list = [((my_obj - obj[1]) ** 2).sum() for obj in objects]
            dist_list[dist_list.index(0)] = 999
            closest = dist_list.index(min(dist_list))
            if objects[closest][2] == 'r':
                answer = 2
            else:
                answer = 3
                
        elif subtype == 1:
            """furthest-from->rectangle/circle"""
            my_obj = objects[color][1]
            dist_list = [((my_obj - obj[1]) ** 2).sum() for obj in objects]
            furthest = dist_list.index(max(dist_list))
            if objects[furthest][2] == 'r':
                answer = 2
            else:
                answer = 3

        elif subtype == 2:
            """count->1~6"""
            my_obj = objects[color][2]
            count = -1
            for obj in objects:
                if obj[2] == my_obj:
                    count +=1 
            answer = count+4

        rel_answers.append(answer)

    relations = (rel_questions, rel_answers)
    norelations = (norel_questions, norel_answers)
    
    img = img/255.
    dataset = (img, relations, norelations)
    return dataset


print('building test datasets...')
test_datasets = [build_dataset() for _ in range(test_size)]
print('building train datasets...')
train_datasets = [build_dataset(left_out_color=args.nb_heldout_colors) for _ in range(train_size)]
print('saving datasets...')
filename = os.path.join(dirs,'sort-of-clevr-{}.pickle'.format(args.nb_heldout_colors))
with open(filename, 'wb') as f:
    pickle.dump((train_datasets, test_datasets), f)
print('datasets saved at {}'.format(filename))