"""Curated vocabularies. Matching one is a metadata mention, never verification of a place."""
import re
import unicodedata

ARABIC_MARKS = re.compile('[ً-ٰٟـ]')


def normalize(value):
    """Spelling-insensitive key for English transliterations and Arabic orthography."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = ARABIC_MARKS.sub('', text)
    for variants, target in (('أإآ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ؤ', 'و'), ('ئ', 'ي')):
        text = re.sub(f'[{variants}]', target, text)
    text = re.sub(r"[’‘'`ʼʻ‘]", '', text)
    return re.sub(r'[\s_\-]+', ' ', re.sub(r'[^\w\s\-]', ' ', text)).strip()


REGIONS = {
    'riyadh': {'en': 'Riyadh', 'ar': 'الرياض', 'aliases': ['riyadh', 'ar riyad', 'الرياض', 'diriyah', 'الدرعية', 'uyaynah', 'العيينة', 'kafd', 'hittin', 'majmaah', 'المجمعة', 'harmah', 'حرمة', 'al kharj', 'الخرج']},
    'makkah': {'en': 'Makkah', 'ar': 'مكة المكرمة', 'aliases': ['makkah', 'makkah province', 'mecca', 'مكة', 'jeddah', 'jiddah', 'جدة', 'جده', 'taif', 'الطائف', 'al hada', 'الهدا']},
    'madinah': {'en': 'Madinah', 'ar': 'المدينة المنورة', 'aliases': ['madinah', 'medina', 'al madinah al munawwarah', 'المدينة', 'المدينه', 'yanbu', 'ينبع', 'alula', 'al ula', 'العلا', 'ٱلعلا', 'madain saleh', 'madain salih', 'مدائن صالح', 'hegra']},
    'qassim': {'en': 'Al Qassim', 'ar': 'القصيم', 'aliases': ['qassim', 'al qassim', 'alqassim', 'القصيم', 'buraydah', 'بريدة', 'unaizah', 'unayzah', 'عنيزة', 'al bukayriyah', 'البكيرية']},
    'eastern': {'en': 'Eastern Province', 'ar': 'المنطقة الشرقية', 'aliases': ['eastern', 'eastern province', 'الشرقية', 'dammam', 'damam', 'الدمام', 'khobar', 'al khobar', 'الخبر', 'qatif', 'al qatif', 'القطيف', 'jubail', 'الجبيل', 'khafji', 'الخفجي', 'al ahsa', 'alahsa', 'الاحساء', 'hofuf', 'الهفوف', 'ras tanura', 'راس تنوره', 'uqair', 'العقير', 'dhahran', 'الظهران', 'hafar al batin', 'حفر الباطن']},
    'asir': {'en': 'Asir', 'ar': 'عسير', 'aliases': ['asir', 'aseer', 'عسير', 'abha', 'ابها', 'khamis mushait', 'خميس مشيط', 'rijal almaa', 'rijal alma', 'رجال المع', 'soudah', 'السوده', 'bisha', 'بيشه']},
    'tabuk': {'en': 'Tabuk', 'ar': 'تبوك', 'aliases': ['tabuk', 'تبوك', 'haql', 'حقل', 'duba', 'ضبا', 'ضبي', 'alqan', 'علقان']},
    'hail': {'en': 'Hail', 'ar': 'حائل', 'aliases': ['hail', 'حائل', 'حايل', 'jubbah', 'جبه']},
    'northern_borders': {'en': 'Northern Borders', 'ar': 'الحدود الشمالية', 'aliases': ['northern borders', 'الحدود الشماليه', 'arar', 'عرعر', 'rafha', 'رفحاء']},
    'jazan': {'en': 'Jazan', 'ar': 'جازان', 'aliases': ['jazan', 'jizan', 'gazan', 'جازان', 'جيزان', 'farasan', 'فرسان']},
    'najran': {'en': 'Najran', 'ar': 'نجران', 'aliases': ['najran', 'نجران']},
    'al_bahah': {'en': 'Al Bahah', 'ar': 'الباحة', 'aliases': ['al bahah', 'al baha', 'albaha', 'الباحة', 'الباحه', 'baljurashi', 'بلجرشي', 'al mandaq', 'المندق']},
    'al_jawf': {'en': 'Al Jawf', 'ar': 'الجوف', 'aliases': ['al jawf', 'aljouf', 'al jouf', 'الجوف', 'sakaka', 'سكاكا', 'dumat al jandal', 'دومه الجندل']},
}
OUTSIDE_SAUDI = {normalize(v) for v in ('المنامة', 'manama', 'bahrain', 'البحرين')}
# Names that place a photo in a city without identifying anything within it.
CITIES = {normalize(v) for v in (
    'riyadh', 'الرياض', 'jeddah', 'جدة', 'dammam', 'damam', 'الدمام', 'khobar', 'الخبر', 'jubail', 'الجبيل', 'khafji', 'الخفجي',
    'qatif', 'القطيف', 'yanbu', 'ينبع', 'tabuk', 'تبوك', 'hail', 'حائل', 'حايل', 'abha', 'ابها', 'haql', 'حقل', 'arar', 'عرعر',
    'najran', 'نجران', 'sakaka', 'سكاكا', 'makkah', 'madinah', 'taif', 'الطائف', 'ras tanura', 'راس تنورة', 'al baha', 'الباحة',
    'jazan', 'jizan', 'جازان', 'جيزان', 'saudi', 'saudi arabia', 'السعودية', 'ksa',
)}
# Features commonly shared across a city: evidence for a regional experience, not one destination.
CITY_FEATURE_TYPES = {'beach', 'corniche', 'park', 'port', 'desert', 'mountain', 'valley'}

# Known alias groups so spelling variants merge. region is context; nothing here is verification.
GAZETTEER = [
    {'name': 'Al Masmak Palace', 'ar': 'قصر المصمك', 'type': 'fort', 'region': 'riyadh', 'aliases': ['masmak', 'al masmak', 'masmak fort', 'masmak palace', 'al masmak palace', 'المصمك', 'قصر المصمك']},
    {'name': 'Wadi Namar', 'ar': 'وادي نمار', 'type': 'valley', 'region': 'riyadh', 'aliases': ['wadi namar', 'namar valley', 'وادي نمار']},
    {'name': 'Wadi Hanifa', 'ar': 'وادي حنيفة', 'type': 'valley', 'region': 'riyadh', 'aliases': ['wadi hanifa', 'wadi hanifah', 'hanifa valley', 'وادي حنيفة']},
    {'name': 'Wadi Al Disah', 'ar': 'وادي الديسة', 'type': 'valley', 'region': 'tabuk', 'aliases': ['al disah', 'disah', 'al dessa', 'al dessa valley', 'wadi al disah', 'wadi disah', 'الديسة', 'وادي الديسة']},
    {'name': 'Dhi Ain Village', 'ar': 'قرية ذي عين', 'type': 'village', 'region': 'al_bahah', 'aliases': ['dhi ain', 'thee ain', 'zee ain', 'ذي عين', 'قرية ذي عين']},
    {'name': 'Rijal Almaa', 'ar': 'رجال ألمع', 'type': 'village', 'region': 'asir', 'aliases': ['rijal almaa', 'rijal alma', 'رجال المع', 'رجال ألمع']},
    {'name': 'Farasan Islands', 'ar': 'جزر فرسان', 'type': 'island', 'region': 'jazan', 'aliases': ['farasan', 'farasan island', 'farasan islands', 'جزيرة فرسان', 'جزر فرسان', 'فرسان']},
    {'name': 'Maraya', 'ar': 'مرايا', 'type': 'venue', 'region': 'madinah', 'aliases': ['maraya', 'مرايا']},
    {'name': 'Hegra', 'ar': 'الحجر', 'type': 'archaeological_site', 'region': 'madinah', 'aliases': ['hegra', 'madain saleh', 'madain salih', 'مدائن صالح']},
    {'name': 'Jabal Al Qarah', 'ar': 'جبل القارة', 'type': 'mountain', 'region': 'eastern', 'aliases': ['jabal al qarah', 'alqara mount', 'al qara mount', 'al qarah', 'جبل القارة']},
    {'name': "Rub' al Khali", 'ar': 'الربع الخالي', 'type': 'desert', 'region': None, 'aliases': ['rub al khali', 'empty quarter', 'الربع الخالي']},
    {'name': 'Al Soudah', 'ar': 'السودة', 'type': 'mountain', 'region': 'asir', 'aliases': ['soudah', 'al soudah', 'السودة']},
    {'name': 'Al Hada', 'ar': 'الهدا', 'type': 'mountain', 'region': 'makkah', 'aliases': ['al hada', 'الهدا']},
    {'name': 'Al Uqair', 'ar': 'العقير', 'type': 'port', 'region': 'eastern', 'aliases': ['uqair', 'al uqair', 'ميناء العقير', 'العقير']},
    {'name': 'Dumat Al Jandal', 'ar': 'دومة الجندل', 'type': 'heritage_area', 'region': 'al_jawf', 'aliases': ['dumat al jandal', 'دومة الجندل']},
    {'name': 'Bir Hima', 'ar': 'بئر حمى', 'type': 'archaeological_site', 'region': 'najran', 'aliases': ['bir hima', 'بئر حمى']},
    {'name': 'Historic Jeddah (Al Balad)', 'ar': 'جدة التاريخية', 'type': 'heritage_area', 'region': 'makkah', 'aliases': ['al balad', 'albalad', 'historic jeddah', 'جدة التاريخية']},
    {'name': 'Boulevard World', 'ar': 'بوليفارد وورلد', 'type': 'venue', 'region': 'riyadh', 'aliases': ['boulevard world', 'riyadh boulevard world']},
    {'name': 'Boulevard City', 'ar': 'بوليفارد سيتي', 'type': 'venue', 'region': 'riyadh', 'aliases': ['boulevard city', 'boulevard riyadh city']},
]

# English pattern words mapped to a destination type.
SUFFIX_TYPES = {
    'valley': 'valley', 'mountain': 'mountain', 'mount': 'mountain', 'beach': 'beach', 'island': 'island', 'palace': 'palace',
    'fort': 'fort', 'fortress': 'fort', 'castle': 'fort', 'village': 'village', 'dam': 'dam', 'lake': 'lake', 'oasis': 'oasis',
    'park': 'park', 'museum': 'museum', 'rock': 'rock_formation', 'mosque': 'mosque', 'port': 'port', 'corniche': 'corniche',
    'canyon': 'canyon', 'cave': 'cave', 'reserve': 'nature_reserve', 'waterfall': 'waterfall', 'falls': 'waterfall',
}
PREFIX_TYPES = {'wadi': 'valley', 'jabal': 'mountain', 'jebel': 'mountain', 'palace': 'palace', 'qasr': 'palace'}
ARABIC_TYPES = {
    'وادي': 'valley', 'جبل': 'mountain', 'قصر': 'palace', 'قلعة': 'fort', 'حصن': 'fort', 'قرية': 'village', 'شاطئ': 'beach',
    'شلال': 'waterfall', 'جزيرة': 'island', 'متحف': 'museum', 'محمية': 'nature_reserve', 'كهف': 'cave', 'ميناء': 'port',
    'حصاة': 'rock_formation', 'صخرة': 'rock_formation', 'بحيرة': 'lake', 'جامع': 'mosque', 'مسجد': 'mosque', 'سد': 'dam', 'قاع': 'plain',
}
# Words that cannot be the distinctive part of a place name.
GENERIC_NAME_WORDS = {
    'the', 'a', 'an', 'old', 'historic', 'historical', 'ancient', 'beautiful', 'great', 'big', 'small', 'new', 'my', 'our', 'this',
    'rock', 'sand', 'sunset', 'sunrise', 'desert', 'sea', 'red', 'green', 'saudi', 'arabia', 'ksa', 'explore', 'from', 'in', 'at',
    'on', 'of', 'to', 'and', 'trip', 'view', 'night', 'morning', 'mountain', 'valley', 'national', 'heritage', 'marble',
}
TRAILING_NAME_WORDS = {'is', 'was', 'are', 'in', 'at', 'on', 'of', 'the', 'and', 'by', 'to', 'it', 'has', 'near'}
ARABIC_STOP_WORDS = {normalize(v) for v in (
    'في', 'من', 'الى', 'إلى', 'عند', 'على', 'مع', 'بعد', 'قبل', 'وقت', 'اثناء', 'قديما', 'قديم', 'القديم', 'القديمة', 'جميل', 'جميلة',
    'الجميل', 'الجميلة', 'كانت', 'هذا', 'هذه', 'ذلك', 'لا', 'ما', 'و', 'بـ', 'ب',
)}

# Coastal evidence from tags alone is not trusted for landlocked regions (tag spam).
INLAND_REGIONS = {'riyadh', 'qassim', 'hail', 'al_jawf', 'northern_borders', 'najran'}
# Palm trees alone do not show farming: Saudi beaches and city parks are full of them.
AMBIGUOUS_AGRICULTURE_TERMS = {'palm', 'palms', 'palm tree', 'palm trees', 'نخيل', 'نخل', 'نخله'}
MAX_TRUSTED_TAGS = 20

THEMES = {
    'agricultural_tourism': {'en': 'Agricultural and farm tourism', 'ar': 'السياحة الزراعية', 'visual': {'rural'},
        'terms': ['palm', 'palms', 'palm tree', 'palm trees', 'date palm', 'date farm', 'date farms', 'dates farm', 'farm', 'farms', 'farmland', 'orchard', 'harvest', 'agriculture', 'نخيل', 'نخل', 'نخله', 'مزارع', 'مزرعة', 'التمر', 'تمور', 'بستان', 'حصاد']},
    'coastal_marine': {'en': 'Coastal and marine experiences', 'ar': 'التجارب الساحلية والبحرية', 'visual': {'coastal'},
        'terms': ['beach', 'beaches', 'sea', 'seascape', 'red sea', 'coast', 'coastal', 'corniche', 'island', 'boat', 'fishing', 'marine', 'dive', 'diving', 'scuba', 'snorkeling', 'coral', 'شاطئ', 'شواطئ', 'بحر', 'كورنيش', 'جزيرة', 'جزر', 'صيد', 'ساحل', 'ميناء', 'قارب']},
    'desert_adventure': {'en': 'Desert landscapes and adventure', 'ar': 'الصحراء والمغامرة', 'visual': {'desert'},
        'terms': ['desert', 'deserts', 'dune', 'dunes', 'empty quarter', 'rub al khali', 'nafud', 'camel', 'camels', 'صحراء', 'صحاري', 'كثبان', 'رمال', 'نفود', 'الربع الخالي', 'ابل', 'جمل']},
    'mountain_highlands': {'en': 'Mountains and highlands', 'ar': 'الجبال والمرتفعات', 'visual': {'mountain'},
        'terms': ['mountain', 'mountains', 'canyon', 'canyons', 'peak', 'highland', 'highlands', 'cliff', 'cliffs', 'snow', 'hiking', 'جبل', 'جبال', 'مرتفعات', 'ثلوج', 'ثلج', 'ضباب', 'قمة']},
    'valleys_waterscapes': {'en': 'Valleys, oases and waterscapes', 'ar': 'الأودية والواحات والمياه', 'visual': set(),
        'terms': ['valley', 'wadi', 'dam', 'waterfall', 'lake', 'oasis', 'وادي', 'اودية', 'شلال', 'سد', 'بحيرة', 'واحة', 'سيول']},
    'heritage_villages_forts': {'en': 'Heritage villages, forts and palaces', 'ar': 'القرى التراثية والحصون والقصور', 'visual': {'historical', 'cultural'},
        'terms': ['heritage', 'old village', 'old town', 'fort', 'fortress', 'castle', 'palace', 'historic', 'ruins', 'mud house', 'old door', 'traditional', 'تراث', 'تراثية', 'قرية قديمة', 'قصر', 'قلعة', 'حصن', 'باب قديم', 'الديرة']},
    'archaeology_rock_art': {'en': 'Archaeology and rock art', 'ar': 'الآثار والنقوش الصخرية', 'visual': set(),
        'terms': ['petroglyph', 'petroglyphs', 'rock art', 'archaeology', 'archaeological', 'ancient civilisation', 'ancient civilization', 'tomb', 'tombs', 'inscription', 'نقوش', 'اثار', 'آثار', 'نقش']},
    'faith_architecture': {'en': 'Mosques and faith architecture', 'ar': 'المساجد والعمارة الدينية', 'visual': set(), 'sensitive': 'Religious sites require cultural review and may limit who can visit; not a default promotional subject.',
        'terms': ['mosque', 'mosques', 'minaret', 'جامع', 'مسجد', 'مساجد']},
    'urban_leisure_events': {'en': 'City life, leisure and events', 'ar': 'الحياة الحضرية والترفيه والفعاليات', 'visual': {'urban'},
        'terms': ['festival', 'celebration', 'boulevard', 'downtown', 'skyline', 'city nights', 'city at night', 'night view', 'kafd', 'kingdom tower', 'fountain', 'مهرجان', 'فعالية', 'احتفال', 'بوليفارد']},
    'wildlife_birdwatching': {'en': 'Wildlife and birdwatching', 'ar': 'الحياة الفطرية ومراقبة الطيور', 'visual': set(),
        'terms': ['bird', 'birds', 'birding', 'harrier', 'falcon', 'wildlife', 'gazelle', 'oryx', 'flamingo', 'طيور', 'طائر', 'صقر', 'غزال', 'حياة فطرية']},
    'night_sky': {'en': 'Stargazing and night skies', 'ar': 'تأمل النجوم وسماء الليل', 'visual': set(),
        'terms': ['milky way', 'stargazing', 'astrophotography', 'starry', 'night sky', 'milkyway', 'نجوم السماء', 'مجرة', 'درب التبانة']},
}
