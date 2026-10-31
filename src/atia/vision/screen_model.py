from importlib.metadata import version,PackageNotFoundError
from atia.vision.model import OpenClipAnalyzer, VisionError
from atia.vision.dimensions import fingerprint
from atia.vision.relevance_prompts import text_catalog


def model_spec():
    try:
        return {'model_name':OpenClipAnalyzer.model_name,'pretrained':OpenClipAnalyzer.pretrained,
                'libraries':{p:version(p) for p in ('open_clip_torch','torch','torchvision','Pillow')},
                'preprocessing':'openclip-default-eval-v1', 'embedding':'L2-normalized-float32'}
    except PackageNotFoundError:
        raise VisionError('Install optional vision dependencies: pip install -r requirements-vision.txt') from None



class ScreeningAnalyzer(OpenClipAnalyzer):
    prompts = text_catalog()

    def encode_images(self, images):
        try:
            with self.torch.inference_mode():
                tensors=self.torch.stack([self.preprocess(image) for image in images]).to(self.device)
                return self.model.encode_image(tensors,normalize=True).float().cpu().numpy()
        except Exception:
            raise VisionError('Screening image encoding failed; reduce batch size or use CPU.') from None

    def compare(self, vectors, stage):
        indexes=[i for i,key in enumerate(self.prompts) if (key.startswith('screen/')) == (stage=='screen')]
        keys=[list(self.prompts)[i] for i in indexes]
        try:
            with self.torch.inference_mode():
                features=self.torch.as_tensor(vectors,device=self.device)
                values=(features @ self.text_features[indexes].T).float().cpu().tolist()
            return [dict(zip(keys,row)) for row in values]
        except Exception:
            raise VisionError('Pretrained image-text comparison failed; no decision inferred.') from None
