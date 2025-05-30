import argparse
import torch
from tqdm import tqdm
import os

from llava.constants import IMAGE_TOKEN_INDEX, DEFAULT_IMAGE_TOKEN, DEFAULT_IM_START_TOKEN, DEFAULT_IM_END_TOKEN
from llava.conversation import conv_templates, SeparatorStyle
from llava.model.builder import load_pretrained_model
from llava.utils import disable_torch_init
from llava.mm_utils import tokenizer_image_token, get_model_name_from_path, KeywordsStoppingCriteria

from PIL import Image

import requests
from PIL import Image
from io import BytesIO
import json


import datetime

def load_image(image_file):
    if image_file.startswith('http') or image_file.startswith('https'):
        response = requests.get(image_file)
        image = Image.open(BytesIO(response.content)).convert('RGB')
    else:
        image = Image.open(image_file).convert('RGB')
    return image
def eval_model(args):
    model_path = args.model_path
    disable_torch_init()
    model_name = get_model_name_from_path(model_path)
    tokenizer, model, image_processor, context_len = load_pretrained_model(model_path, args.model_base, model_name)
    model.sigma = args.sigma
    model = model.cuda()
    qs = args.query
    print(qs)
    if model.config.mm_use_im_start_end:
        qs = DEFAULT_IM_START_TOKEN + DEFAULT_IMAGE_TOKEN + DEFAULT_IM_END_TOKEN + '\n' + qs
    else:
        qs = DEFAULT_IMAGE_TOKEN + '\n' + qs
    
    conv_mode = args.conv_mode
    # conv_mode = "llava_v0"

    if args.conv_mode is not None and conv_mode != args.conv_mode:
        print('[WARNING] the auto inferred conversation mode is {}, while `--conv-mode` is {}, using {}'.format(conv_mode, args.conv_mode, args.conv_mode))
    else:
        args.conv_mode = conv_mode

    conv = conv_templates[args.conv_mode].copy()
    conv.append_message(conv.roles[0], qs)
    conv.append_message(conv.roles[1], None)
    prompt = conv.get_prompt()
    vg_path = args.gt_file_path
    vg_objects = json.load(open('%s/objects.json' %(vg_path)))
    vg_objects = vg_objects[:100]
    image_ids = [obj['image_id'] for obj in vg_objects]
    results = []
    path = args.output_folder

    # Create the folder if it doesn't exist
    if not os.path.exists(path):
        os.makedirs(path)

    for id in tqdm(image_ids):
        image_file = f'{args.image_path}/images2/VG_100K_2/{id}.jpg'
        if not os.path.isfile(image_file):
            image_file = f'{args.image_path}/images/VG_100K/{id}.jpg'

        image = load_image(image_file)
        image_tensor = image_processor.preprocess(image, return_tensors='pt')['pixel_values'].half().cuda()

        input_ids = tokenizer_image_token(prompt, tokenizer, IMAGE_TOKEN_INDEX, return_tensors='pt').unsqueeze(0).cuda()

        stop_str = conv.sep if conv.sep_style != SeparatorStyle.TWO else conv.sep2
        keywords = [stop_str]
        stopping_criteria = KeywordsStoppingCriteria(keywords, tokenizer, input_ids)
        # max_new_tokens=1024,
        with torch.inference_mode():
            output_ids = model.generate(
                input_ids,
                images=image_tensor,
                do_sample=True,
                temperature=0.2,
                max_length=1024,
                use_cache=True,
                stopping_criteria=[stopping_criteria])

        input_token_len = input_ids.shape[1]
        n_diff_input_output = (input_ids != output_ids[:, :input_token_len]).sum().item()
        if n_diff_input_output > 0:
            print(f'[Warning] {n_diff_input_output} output_ids are not the same as the input_ids')
        outputs = tokenizer.batch_decode(output_ids[:, input_token_len:], skip_special_tokens=True)[0]
        outputs = outputs.strip()
        if outputs.endswith(stop_str):
            outputs = outputs[:-len(stop_str)]
        outputs = outputs.strip()
        results.append({'image_id':id, 'path':image_file, 'text':outputs})
        print(id, outputs)

    with open(f"{path}/vg_{args.sigma}.json", "w") as file:
        json.dump(results, file, indent=4)
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=str, default="facebook/opt-350m")
    parser.add_argument("--model-base", type=str, default=None)
    parser.add_argument("--sigma", type=float, default=0)
    parser.add_argument("--gt_file_path", type=str, default='./data/VisualGenome_task')
    parser.add_argument("--image_path", type=str, default='./data')
    parser.add_argument("--query", type=str, default="Describe this image as detail as possible.")
    parser.add_argument("--conv-mode", type=str, default='v1')
    parser.add_argument("--output_folder", type=str, default='./')
    args = parser.parse_args()
    eval_model(args)
