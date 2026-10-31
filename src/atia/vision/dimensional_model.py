from atia.vision.model import OpenClipAnalyzer, VisionError
from atia.vision.dimensions import FLAT_PROMPTS, DIMENSION_PROMPTS, DIMENSION_PROMPT_VERSION


class DimensionalAnalyzer(OpenClipAnalyzer):
    prompts = FLAT_PROMPTS
    prompt_version = DIMENSION_PROMPT_VERSION

    def score_batch(self, images):
        if not images:
            return []
        try:
            with self.torch.inference_mode():
                tensors = self.torch.stack([self.preprocess(image) for image in images]).to(self.device)
                features = self.model.encode_image(tensors, normalize=True)
                values = (features @ self.text_features.T).float().cpu().tolist()
            results = []
            for values_for_image in values:
                flat = dict(zip(self.prompts, values_for_image))
                results.append({dimension: {label: flat[f'{dimension}/{label}'] for label in labels}
                                for dimension, labels in DIMENSION_PROMPTS.items()})
            return results
        except Exception:
            raise VisionError('Batched OpenCLIP inference failed; reduce --batch-size or use CPU.') from None
