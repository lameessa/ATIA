import hashlib
import json

# Comparable descriptions, fixed and versioned by their content hash.
PROMPTS = {
    'mountains': 'A photograph of mountains, rocky peaks, and mountain scenery.',
    'deserts': 'A photograph of a desert landscape with sand dunes or arid plains.',
    'beaches': 'A photograph of a beach, sandy coastline, and the sea.',
    'forests': 'A photograph of a forest, trees, and woodland scenery.',
    'historical_architecture': 'A photograph of historical architecture, old stone buildings, or ancient ruins.',
    'cultural_landmarks': 'A photograph of a cultural landmark, a traditional village, or a heritage monument.',
    'urban_landscapes': 'A photograph of a city skyline, modern buildings, or urban streets.',
    'other': 'A photograph of people, animals, food, vehicles, or an indoor scene.',
}
PROMPT_VERSION = hashlib.sha256(json.dumps(PROMPTS, sort_keys=True).encode()).hexdigest()
