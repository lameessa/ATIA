import os
from pathlib import Path

MODEL_ID='cardiffnlp/twitter-xlm-roberta-base-sentiment'
MODEL_REVISION='f2f1202b1bdeb07342385c3f807f9c07cd8f5cf8'
PREPROCESS_VERSION='flickr-html-text-mentions-urls-v1-max256'


class SentimentError(RuntimeError):
    pass


class SentimentModel:
    def __init__(self,revision,cache_dir='data/sentiment-models',local_files_only=False):
        if not revision or len(revision)!=40:raise ValueError('A pinned Hugging Face commit SHA is required')
        os.environ.setdefault('HF_HOME',str(Path(cache_dir).resolve()/'hf'))
        os.environ.setdefault('HF_HUB_DISABLE_XET','1')
        os.environ['DISABLE_SAFETENSORS_CONVERSION']='true'
        try:
            import torch
            import transformers
            from transformers import AutoTokenizer,AutoModelForSequenceClassification
        except ImportError:
            raise SentimentError('Install requirements-sentiment.txt before inference') from None
        self.model_id=MODEL_ID;self.revision=revision;self.torch=torch
        self.runtime={'torch':torch.__version__,'transformers':transformers.__version__,'device':'cpu'}
        torch.set_num_threads(min(4,torch.get_num_threads()))
        try:
            snapshot=Path(cache_dir)/('models--'+MODEL_ID.replace('/','--'))/'snapshots'/revision
            cached=(snapshot/'config.json').exists() and (snapshot/'pytorch_model.bin').exists()
            source=str(snapshot.resolve()) if cached else MODEL_ID
            self.tokenizer=AutoTokenizer.from_pretrained(source,revision=revision,cache_dir=cache_dir,trust_remote_code=False,local_files_only=local_files_only or cached,fix_mistral_regex=False)
            self.model=AutoModelForSequenceClassification.from_pretrained(source,revision=revision,cache_dir=cache_dir,trust_remote_code=False,local_files_only=local_files_only or cached)
            if cached:self.tokenizer.save_pretrained(snapshot)
            self.model.eval();self.model.requires_grad_(False)
            self.labels={int(k):str(v).lower() for k,v in self.model.config.id2label.items()}
            if set(self.labels.values())!={'positive','negative','neutral'}:raise ValueError('Unexpected model labels')
        except Exception:
            raise SentimentError('Unable to load pinned pretrained sentiment model. Check model files, dependencies, and network access.') from None

    def predict(self,texts):
        import re
        normalized=[re.sub(r'(?<!\w)@\w+','@user',re.sub(r'https?://\S+','http',text)) for text in texts]
        try:
            untruncated=self.tokenizer(normalized,truncation=False,add_special_tokens=True)['input_ids']
            encoded=self.tokenizer(normalized,return_tensors='pt',padding=True,truncation=True,max_length=256)
            with self.torch.inference_mode():
                probabilities=self.model(**encoded).logits.softmax(dim=-1).cpu().tolist()
            results=[]
            for scores,tokens in zip(probabilities,untruncated):
                values={self.labels[i]:float(v) for i,v in enumerate(scores)}
                label=max(values,key=values.get)
                results.append({'label':label,'confidence':values[label],'scores':values,'truncated':len(tokens)>256})
            return results
        except Exception:
            raise SentimentError('Sentiment inference failed for this batch; no fabricated labels stored') from None
