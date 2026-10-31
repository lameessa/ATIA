import html
from html.parser import HTMLParser
import re
import unicodedata

LANGUAGE_VERSION='langid-all-languages-norm-v1-min3-p080-mixed-script'


class TextExtractor(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('br','p','div'):self.parts.append(' ')
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.hidden:self.hidden-=1
        if tag in ('p','div'):self.parts.append(' ')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def clean_comment(value):
    if not isinstance(value,str):return ''
    parser=TextExtractor();parser.feed(value);parser.close()
    return ' '.join(unicodedata.normalize('NFKC',html.unescape(''.join(parser.parts))).split())


class LanguageDetector:
    version=LANGUAGE_VERSION
    def __init__(self):
        try:
            from langid.langid import LanguageIdentifier,model
        except ImportError:
            raise RuntimeError('Install requirements-sentiment.txt for language detection') from None
        self.detector=LanguageIdentifier.from_modelstring(model,norm_probs=True)

    def detect(self,text):
        text=re.sub(r'https?://\S+|(?<!\w)@\w+',' ',text)
        letters=[c for c in text if c.isalpha()]
        if not letters:return {'language':'und','confidence':None,'status':'empty_or_nonlinguistic'}
        if len(letters)<3:return {'language':'und','confidence':None,'status':'language_uncertain'}
        arabic=sum('\u0600'<=c<='\u06ff' for c in letters)
        latin=sum('LATIN' in unicodedata.name(c,'') for c in letters)
        if arabic>=3 and latin>=3:return {'language':'mixed','confidence':None,'status':'mixed_language_review'}
        language,confidence=self.detector.classify(text)
        confidence=float(confidence)
        status='ready' if language in {'ar','en'} and confidence>=.8 else 'language_uncertain' if confidence<.8 else 'unsupported_language'
        return {'language':language,'confidence':confidence,'status':status}
