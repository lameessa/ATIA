"""Versioned prompts and conservative, configurable interpretation heuristics."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

DIMENSION_PROMPTS = {
    'environment': {
        'urban': 'A photograph of an urban landscape with city streets and modern buildings.',
        'desert': 'A photograph of a desert landscape with dunes and arid sandy plains.',
        'mountain': 'A photograph of a mountain landscape with high rocky peaks.',
        'coastal': 'A photograph of a coastal landscape with beaches and the sea.',
        'forest': 'A photograph of a forest landscape with dense trees and woodland.',
        'rural': 'A photograph of a rural landscape with farmland, fields, and countryside.',
        'historical': 'A photograph of a historical landscape with old buildings and ancient ruins.',
        'cultural': 'A photograph of a cultural landscape with traditional villages and heritage landmarks.',
    },
    'elements': {
        'trees': 'A photograph showing trees.',
        'vegetation': 'A photograph showing green vegetation, bushes, or plants.',
        'cars': 'A photograph showing cars.',
        'roads': 'A photograph showing roads.',
        'buildings': 'A photograph showing buildings.',
        'people': 'A photograph showing people.',
        'water': 'A photograph showing water.',
        'rock_formations': 'A photograph showing natural rock formations.',
        'sand': 'A photograph showing sand.',
        'traditional_architecture': 'A photograph showing traditional architecture.',
    },
    'conditions': {
        'daytime': 'An outdoor photograph taken in daylight during the day.',
        'nighttime': 'An outdoor photograph taken at night in darkness.',
        'sunrise': 'An outdoor photograph taken at sunrise with dawn light.',
        'sunset': 'An outdoor photograph taken at sunset with evening light.',
        'cloudy': 'An outdoor photograph with overcast cloudy skies.',
        'foggy': 'An outdoor photograph in fog or mist with low visibility.',
    },
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


FLAT_PROMPTS = {f'{dimension}/{label}': text for dimension, labels in DIMENSION_PROMPTS.items() for label, text in labels.items()}
DIMENSION_PROMPT_VERSION = fingerprint(DIMENSION_PROMPTS)


@dataclass(frozen=True)
class Thresholds:
    # Uncalibrated starting heuristics, not validated detection operating points.
    environment_min: float = 0.25
    environment_margin: float = 0.03
    element_min: float = 0.25
    condition_min: float = 0.25
    lighting_margin: float = 0.03

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f'{key} must be a finite number')
            if not (0 <= value <= (2 if 'margin' in key else 1)):
                raise ValueError(f'{key} is outside its allowed range')

    @property
    def version(self):
        return fingerprint(asdict(self))

    @classmethod
    def load(cls, path=None):
        if not path:
            return cls()
        from pathlib import Path
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('Threshold file must contain only supported threshold names')
        return cls(**data)


def interpret(dimension, scores, thresholds):
    if set(scores) != set(DIMENSION_PROMPTS[dimension]) or not all(isinstance(v, (int, float)) and math.isfinite(v) and -1.0001 <= v <= 1.0001 for v in scores.values()):
        raise ValueError('Invalid dimensional similarity scores')
    ranked = sorted(scores, key=scores.get, reverse=True)
    if dimension == 'environment':
        strongest, runner_up = ranked[:2]
        margin = scores[strongest] - scores[runner_up]
        uncertain = scores[strongest] < thresholds.environment_min or margin < thresholds.environment_margin
        return {'strongest_match': strongest, 'strongest_similarity': scores[strongest],
                'runner_up': runner_up, 'margin': margin, 'uncertain': uncertain,
                'label': None if uncertain else strongest,
                'status': 'uncertain' if uncertain else 'possible_match'}
    minimum = thresholds.element_min if dimension == 'elements' else thresholds.condition_min
    possible = [label for label in ranked if scores[label] >= minimum]
    per_label = {label: {'similarity': scores[label], 'status': 'possible_match' if label in possible else 'uncertain'} for label in scores}
    result = {'possible_matches': possible, 'per_label': per_label,
              'uncertain': not bool(possible), 'status': 'possible_matches' if possible else 'uncertain'}
    if dimension == 'conditions':
        lighting = sorted(('daytime', 'nighttime', 'sunrise', 'sunset'), key=scores.get, reverse=True)
        strongest = lighting[0]
        margin = scores[strongest] - scores[lighting[1]]
        accepted = scores[strongest] >= minimum and margin >= thresholds.lighting_margin
        # Weather can coexist with light (e.g. daytime + cloudy). Do not force
        # one label across weather and lighting or infer capture-clock timestamps.
        result['lighting'] = {'strongest_match': strongest, 'margin': margin,
                              'label': strongest if accepted else None, 'uncertain': not accepted}
        result['weather_matches'] = [key for key in ('cloudy', 'foggy') if key in possible]
        result['uncertain'] = not accepted or not bool(result['weather_matches'])
        result['status'] = ('partial_uncertain' if possible else 'uncertain') if result['uncertain'] else 'possible_matches'
    return result
