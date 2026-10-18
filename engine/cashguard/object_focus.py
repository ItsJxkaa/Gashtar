"""Local human-trained object proposals for optional magnified visual context.

Detector absence is never evidence of an omitted action. Proposals only allocate
image resolution; the VLM still sees the original chronological frame sequence.
"""
from pathlib import Path


class ObjectFocus:
    def __init__(self, path):
        import torch
        from torchvision.models.detection import fasterrcnn_resnet50_fpn_v2
        from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
        self.torch=torch
        checkpoint=torch.load(Path(path),map_location='cpu',weights_only=True)
        if checkpoint['architecture']!='torchvision/fasterrcnn_resnet50_fpn_v2':
            raise ValueError('Unsupported detector checkpoint')
        config=checkpoint.get('detector_config',{'min_size':640,'max_size':1024,'small_anchors':False})
        self.model=fasterrcnn_resnet50_fpn_v2(weights=None,weights_backbone=None,min_size=config['min_size'],max_size=config['max_size'],
                                             box_detections_per_img=30)
        if config.get('small_anchors'):
            from torchvision.models.detection.anchor_utils import AnchorGenerator
            self.model.rpn.anchor_generator=AnchorGenerator(((16,),(32,),(64,),(128,),(256,)),((.5,1.,2.),)*5)
        self.model.roi_heads.box_predictor=FastRCNNPredictor(self.model.roi_heads.box_predictor.cls_score.in_features,6)
        self.model.load_state_dict(checkpoint['state_dict'],strict=True)
        self.model.to('cuda').eval()

    def crops(self, pictures, budget):
        if budget<=0:
            return {}
        from torchvision.transforms.functional import pil_to_tensor
        torch=self.torch
        proposals=[]
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            for index,picture in enumerate(pictures):
                prediction=self.model([pil_to_tensor(picture).float().to('cuda')/255])[0]
                mask=((prediction['labels']==1)|(prediction['labels']==2))&(prediction['scores']>=.5)
                boxes=prediction['boxes'][mask].float().cpu()
                labels=prediction['labels'][mask].cpu()
                scores=prediction['scores'][mask].float().cpu()
                if not len(boxes):
                    continue
                # Prefer a rare ID proposal; retain hands and surrounding context.
                chosen=max(range(len(boxes)),key=lambda i:(int(labels[i])==2,float(scores[i])))
                x1,y1,x2,y2=boxes[chosen].tolist()
                w,h=picture.size
                cx,cy=(x1+x2)/2,(y1+y2)/2
                cw,ch=max(128,(x2-x1)*3),max(128,(y2-y1)*3)
                rect=(max(0,int(cx-cw/2)),max(0,int(cy-ch/2)),min(w,int(cx+cw/2)),min(h,int(cy+ch/2)))
                if (rect[2]-rect[0])*(rect[3]-rect[1])>.8*w*h:
                    continue
                proposals.append((int(labels[chosen])==2,float(scores[chosen]),index,rect))
        selected=sorted(proposals,reverse=True)[:budget]
        crops={}
        for _,_,index,rect in selected:
            crop=pictures[index].crop(rect)
            scale=min(3,768/max(crop.size))
            if scale>1:
                crop=crop.resize((round(crop.width*scale),round(crop.height*scale)))
            crops[index]=crop
        return crops
