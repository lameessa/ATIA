"""Lazy imports keep the original collection CLI independent of PyTorch."""
import math
import os
from pathlib import Path
from atia.vision.prompts import PROMPTS, PROMPT_VERSION


class VisionError(RuntimeError):
    pass


class OpenClipAnalyzer:
    model_name = 'ViT-B-32'
    pretrained = 'laion2b_s34b_b79k'
    prompt_version = PROMPT_VERSION
    prompts = PROMPTS

    def __init__(self, cache_dir='data/models', device='cpu'):
        os.environ.setdefault('HF_HOME', str(Path(cache_dir).resolve() / 'hf'))
        os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
        try:
            import torch
            import open_clip
        except ImportError:
            raise VisionError('Install optional vision dependencies: pip install -r requirements-vision.txt') from None
        self.torch = torch
        self.device = device
        if device == 'mps' and not torch.backends.mps.is_available():
            raise VisionError('MPS is unavailable on this Mac; use --device cpu.')
        torch.set_num_threads(min(4, torch.get_num_threads()))
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        try:
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                self.model_name, pretrained=self.pretrained, device=device, cache_dir=cache_dir)
            self.model.eval()
            self.model.requires_grad_(False)
            tokenizer = open_clip.get_tokenizer(self.model_name)
            with torch.inference_mode():
                self.text_features = self.model.encode_text(
                    tokenizer(list(self.prompts.values())).to(device), normalize=True)
        except Exception:
            raise VisionError('Unable to load pretrained OpenCLIP weights or encode prompts. Check network access, disk space, and device availability.') from None
        self.library_version = open_clip.__version__

    def score(self, image):
        try:
            with self.torch.inference_mode():
                tensor = self.preprocess(image).unsqueeze(0).to(self.device)
                features = self.model.encode_image(tensor, normalize=True)
                values = (features @ self.text_features.T).squeeze(0).float().cpu().tolist()
            scores = dict(zip(self.prompts, values))
            if len(scores) != len(self.prompts) or not all(math.isfinite(v) and -1.0001 <= v <= 1.0001 for v in scores.values()):
                raise ValueError('Invalid cosine similarity')
            return scores
        except Exception:
            raise VisionError('OpenCLIP inference failed for this image; no scores stored.') from None
