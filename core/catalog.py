"""
Catalogue answers: recommendations and brewing advice, built from Tea rows.

Everything in this module reads the database and composes sentences from real
fields. The language model is never asked what to recommend or how to brew
anything, so it cannot invent a tea, a price, a temperature or a steep time.
The most the model is allowed to do, in assistant.py, is reword the one
introductory sentence this module hands it.
"""

import logging
import re

from django.db import DatabaseError

from core import weather as weather_module
from core.models import Tea

log = logging.getLogger("maison")

# Words that carry no meaning for matching.
STOPWORDS = {
    "a", "about", "after", "all", "am", "an", "and", "any", "are", "as", "at",
    "be", "been", "but", "by", "can", "could", "do", "does", "doing", "for",
    "from", "get", "give", "good", "got", "has", "have", "how", "i", "if", "in",
    "is", "it", "its", "like", "me", "much", "my", "need", "of", "on", "or",
    "please", "should", "so", "some", "something", "tea", "teas", "tell", "than",
    "that", "the", "their", "them", "then", "there", "these", "they", "this",
    "to", "up", "use", "want", "was", "we", "what", "when", "which", "will",
    "with", "would", "you", "your",
}

# Visitor words to mood vocabulary. Longest phrases are checked first so
# "hot day" does not match on "hot" alone.
MOOD_PHRASES = [
    ("calm", ["wind down", "winding down", "before bed", "help me sleep", "can't sleep",
              "cannot sleep", "stressed out"]),
    ("focus", ["help me focus", "stay awake", "keep me awake", "need to study",
               "concentrate better"]),
    ("morning", ["first thing", "wake up", "with breakfast", "start the day"]),
    ("afternoon", ["mid afternoon", "tea time", "teatime", "four o'clock"]),
    ("evening", ["after dinner", "late at night", "before bed", "this evening",
                 "tonight"]),
    ("comfort", ["cold day", "rainy day", "feel better", "curl up"]),
    ("iced", ["cold brew", "over ice", "iced tea", "hot day", "hot weather",
              "cool me down", "in this heat"]),
    ("digestive", ["heavy meal", "ate too much", "after eating", "settle my stomach",
                   "feel bloated", "too full"]),
]

MOOD_WORDS = {
    "calm": {"calm", "calming", "relax", "relaxing", "relaxed", "unwind", "soothing",
             "sleep", "sleepy", "bedtime", "anxious", "anxiety", "stress", "stressed",
             "quiet", "peaceful"},
    "focus": {"focus", "focused", "concentrate", "concentration", "study", "studying",
              "work", "working", "alert", "awake", "productive", "deadline", "revision",
              "exam"},
    "morning": {"morning", "mornings", "breakfast", "early", "sunrise"},
    "afternoon": {"afternoon", "afternoons", "lunch", "midday"},
    "evening": {"evening", "evenings", "night", "nights", "tonight", "dinner", "late",
                "supper"},
    "comfort": {"comfort", "comforting", "cosy", "cozy", "cold", "chilly", "rain",
                "rainy", "winter", "warming", "warm", "monsoon", "unwell", "ill",
                "sick", "flu", "cough"},
    "iced": {"iced", "ice", "chilled", "cool", "cooling", "summer", "refreshing",
             "refreshment", "heat", "hot", "humid", "thirsty"},
    "digestive": {"digestion", "digestive", "digest", "stomach", "bloated", "bloating",
                  "full", "heavy", "nausea", "queasy", "indigestion"},
}

CATEGORY_WORDS = {
    "green": {"green", "sencha", "gyokuro", "longjing", "jasmine"},
    "black": {"black", "assam", "darjeeling", "nilgiri", "ceylon", "keemun",
              "breakfast", "lapsang"},
    "oolong": {"oolong", "tieguanyin", "wulong", "dongding", "rock"},
    "white": {"white", "silver", "peony", "needle"},
    "dark": {"dark", "puer", "pu-erh", "puerh", "shou", "sheng", "fermented", "liubao"},
    "matcha": {"matcha", "whisked", "usucha"},
    "tisane": {"tisane", "tisanes", "herbal", "herb", "herbs", "infusion", "chamomile",
               "rooibos", "tulsi", "hibiscus", "lemongrass", "caffeinefree", "decaf",
               "decaffeinated", "flower", "floral"},
    "blend": {"blend", "blends", "chai", "masala", "earl", "grey", "bergamot", "kahwa",
              "spiced", "spice", "spicy"},
}

BREW_WORDS = {
    "brew", "brewing", "steep", "steeping", "infuse", "temperature", "temp", "hot",
    "degrees", "water", "grams", "gram", "spoon", "teaspoon", "resteep", "resteeps",
    "long", "minutes", "seconds", "make", "prepare", "ratio", "bitter",
}

RECOMMEND_WORDS = {
    "recommend", "recommendation", "recommendations", "suggest", "suggestion",
    "suggestions", "advise", "pick", "choose", "choice", "best", "drink", "try",
    "looking", "mood", "fancy",
}

TODAY_WORDS = {"today", "now", "weather", "outside", "right"}

CAFFEINE_NONE_PHRASES = [
    "no caffeine", "caffeine free", "caffeine-free", "without caffeine",
    "zero caffeine", "free of caffeine", "decaf", "decaffeinated", "caffiene free",
    "no caffiene",
]
CAFFEINE_LOW_PHRASES = ["low caffeine", "little caffeine", "less caffeine",
                        "not much caffeine", "light on caffeine"]
CAFFEINE_HIGH_PHRASES = ["high caffeine", "lots of caffeine", "most caffeine",
                         "strongest", "really strong", "very strong", "plenty of caffeine"]


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed and plural 's' trimmed."""
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    out = []
    for word in words:
        word = word.strip("'")
        if not word or word in STOPWORDS:
            continue
        out.append(stem(word))
    return out


def stem(word: str) -> str:
    """
    Reduce a word to a crude stem, enough for keyword overlap.

    The rules must be consistent in both directions: an earlier version mapped
    "tastes" to "tast" while leaving "taste" alone, so a question about tea
    tasting bitter never matched the FAQ about tea tasting bitter. Singular and
    plural forms of the same word have to land on the same stem.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]
    # "boxes", "dishes", "watches": the e belongs to the plural.
    if len(word) > 4 and word.endswith("es") and word[-3] in "sxzh":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def detect_moods(message: str) -> list[str]:
    lowered = (message or "").lower()
    found: list[str] = []

    for mood, phrases in MOOD_PHRASES:
        if any(phrase in lowered for phrase in phrases) and mood not in found:
            found.append(mood)

    tokens = set(tokenize(message))
    for mood, words in MOOD_WORDS.items():
        if tokens & words and mood not in found:
            found.append(mood)
    return found


def detect_categories(message: str) -> list[str]:
    tokens = set(tokenize(message))
    # Normalise "pu erh" and "caffeine free" style spacing before matching.
    squashed = re.sub(r"[^a-z]", "", (message or "").lower())
    found = []
    for category, words in CATEGORY_WORDS.items():
        if tokens & words:
            found.append(category)
            continue
        if any(len(word) > 5 and word in squashed for word in words):
            found.append(category)
    return found


def detect_caffeine(message: str) -> str | None:
    lowered = (message or "").lower()
    if any(phrase in lowered for phrase in CAFFEINE_NONE_PHRASES):
        return "none"
    if any(phrase in lowered for phrase in CAFFEINE_LOW_PHRASES):
        return "low"
    if any(phrase in lowered for phrase in CAFFEINE_HIGH_PHRASES):
        return "high"
    return None


def find_named_tea(message: str):
    """
    The Tea whose name the visitor wrote, or None.

    Matches on the longest name first so "Darjeeling First Flush, Jungpana"
    wins over a bare "Darjeeling" if both would match.
    """
    lowered = (message or "").lower()
    if not lowered.strip():
        return None
    try:
        teas = list(Tea.objects.all())
    except DatabaseError:
        return None

    best = None
    best_length = 0
    for tea in teas:
        # Try the full name, then each distinctive word of it.
        candidates = [tea.name.lower()]
        candidates += [
            part.strip()
            for part in re.split(r"[,\s]+", tea.name.lower())
            if len(part.strip()) > 4 and part.strip() not in {"first", "flush", "house",
                                                              "blend", "aged", "spring",
                                                              "medium", "roast", "whole",
                                                              "winter", "picking",
                                                              "ceremonial", "pressed",
                                                              "smoked", "cold"}
        ]
        for candidate in candidates:
            if candidate and candidate in lowered and len(candidate) > best_length:
                best = tea
                best_length = len(candidate)
    return best


def wants_brewing(message: str) -> bool:
    tokens = set(tokenize(message))
    lowered = (message or "").lower()
    if "how do i brew" in lowered or "how to brew" in lowered or "how long" in lowered:
        return True
    return bool(tokens & BREW_WORDS)


def wants_recommendation(message: str) -> bool:
    tokens = set(tokenize(message))
    lowered = (message or "").lower()
    if "what should i drink" in lowered or "what do you recommend" in lowered:
        return True
    return bool(tokens & RECOMMEND_WORDS)


def wants_today(message: str) -> bool:
    tokens = set(tokenize(message))
    lowered = (message or "").lower()
    if "today" in lowered or "right now" in lowered or "weather" in lowered:
        return True
    return bool(tokens & TODAY_WORDS)


def has_catalogue_intent(message: str) -> bool:
    """
    Whether this message is the catalogue's business.

    Deliberately broad: if it looks like it is about choosing or making tea, we
    would rather answer from real rows than hand it to the model.
    """
    if not (message or "").strip():
        return False
    return bool(
        wants_recommendation(message)
        or wants_brewing(message)
        or detect_moods(message)
        or detect_categories(message)
        or detect_caffeine(message)
        or find_named_tea(message)
    )


def score_tea(tea: Tea, *, moods, categories, caffeine, tokens, weather_categories) -> float:
    """
    Transparent scoring. Every term here is explainable in a viva.
    """
    score = 0.0

    for mood in moods:
        if mood in tea.mood_list:
            score += 3.0

    if tea.category in categories:
        score += 3.0

    if caffeine:
        if tea.caffeine == caffeine:
            score += 4.0
        elif caffeine == "none":
            # A hard constraint: never offer caffeine to someone who asked for none.
            score -= 50.0
        elif caffeine == "low" and tea.caffeine in {"none", "low"}:
            score += 2.0
        elif caffeine == "high" and tea.caffeine == "medium":
            score += 1.0

    # Exact note matches first, then near matches so "malty" finds the note
    # "malt" and "smoky" finds "smoke". Only for words long enough that a
    # shared prefix means something.
    note_tokens = set(tokenize(tea.flavour_notes))
    exact_notes = note_tokens & tokens
    score += 2.0 * len(exact_notes)
    for token in tokens - exact_notes:
        if len(token) < 4:
            continue
        if any(
            len(note) >= 4 and (note.startswith(token[:4]) or token.startswith(note[:4]))
            for note in note_tokens
        ):
            score += 1.5

    name_tokens = set(tokenize(tea.name))
    score += 6.0 * len(name_tokens & tokens)

    # Someone asking for something calming, or for the evening, is asking to be
    # left alone by the caffeine even if they did not say so.
    if "calm" in moods or "evening" in moods:
        score += {"none": 2.0, "low": 1.0, "medium": 0.0, "high": -1.5}.get(
            tea.caffeine, 0.0
        )

    if tea.category in weather_categories:
        score += 2.0

    score += 1.0 if tea.in_stock else -5.0

    # Stable, deliberate tie-break so the same question gives the same answer.
    score -= tea.order / 10000.0
    return score


def rank(message: str, *, weather_info=None, shortlist=None, limit=3) -> list[Tea]:
    """The ranked teas for a message. Empty list if the database is unavailable."""
    try:
        teas = list(Tea.objects.all())
    except DatabaseError as exc:
        log.warning("catalogue ranking failed, database unavailable: %s", exc)
        return []

    moods = detect_moods(message)
    categories = detect_categories(message)
    caffeine = detect_caffeine(message)
    tokens = set(tokenize(message))
    weather_categories = set((weather_info or {}).get("categories") or [])
    if weather_info and not moods:
        mood = weather_info.get("mood")
        if mood:
            moods = [mood]

    shortlist = set(shortlist or [])

    scored = []
    for tea in teas:
        value = score_tea(
            tea,
            moods=moods,
            categories=categories,
            caffeine=caffeine,
            tokens=tokens,
            weather_categories=weather_categories,
        )
        if tea.slug in shortlist:
            # The visitor already saved this one, so lean towards it.
            value += 2.5
        scored.append((value, tea))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    # Drop anything the caffeine constraint pushed negative.
    return [tea for value, tea in scored[:limit] if value > 0]


def tea_line(tea: Tea) -> str:
    """One tea, described from its row."""
    return (
        f"{tea.name}. {tea.origin}, {tea.caffeine_phrase}, "
        f"notes of {', '.join(tea.note_list)}. {tea.brewing_sentence()} "
        f"{tea.price_inr_50g} rupees for 50 g."
    )


def brewing_answer(tea: Tea) -> dict:
    """A full brewing answer for one named tea, straight from the row."""
    lines = [
        f"{tea.name}, brewed the way we brew it:",
        f"Water at {tea.brew_temp_c} C.",
        f"{tea.grams_per_200ml:g} g of leaf per 200 ml.",
        f"Steep the first infusion for {tea.steep_label}.",
    ]
    if tea.resteeps == 1:
        lines.append("It will give one more steep. Add about 30 seconds to it.")
    elif tea.resteeps > 1:
        lines.append(
            f"It will give {tea.resteeps} more steeps. Add about 30 seconds to each one."
        )
    else:
        lines.append("It is a single-steep tea, so there is no need to keep the leaf.")
    lines.append(f"Expect {', '.join(tea.note_list)}. Good with {tea.pairing.lower()}")

    return {
        "reply": "\n".join(lines),
        "intro": f"{tea.name}, brewed the way we brew it:",
        "source": "catalog",
        "teas": [{"name": tea.name, "url": tea.get_absolute_url(), "slug": tea.slug}],
    }


def _intro_for(message: str, teas: list[Tea], weather_info) -> str:
    moods = detect_moods(message)
    caffeine = detect_caffeine(message)
    count = len(teas)
    word = "one" if count == 1 else ("two" if count == 2 else "three")

    if weather_info and wants_today(message):
        return f"{weather_info['reason']} {word.capitalize()} from the shelf:"
    if caffeine == "none":
        return f"Nothing from the tea plant, so no caffeine at all. {word.capitalize()} to consider:"
    if moods:
        return f"For {moods[0]}, {word} that work:"
    return f"{word.capitalize()} I would pull off the shelf:"


def answer(message: str, *, shortlist=None, city=None) -> dict | None:
    """
    The catalogue's answer to a message, or None if it has nothing to say.

    Returns {reply, intro, source, teas, weather?}. `intro` is separated out so
    assistant.py may hand just that sentence to the model to reword.
    """
    if not has_catalogue_intent(message):
        return None

    weather_info = None
    if wants_today(message):
        weather_info = weather_module.for_city(city)

    # "How do I brew the gyokuro" is a brewing question about a specific tea.
    named = find_named_tea(message)
    if named is not None and wants_brewing(message) and not wants_recommendation(message):
        return brewing_answer(named)

    teas = rank(message, weather_info=weather_info, shortlist=shortlist, limit=3)

    if not teas:
        if detect_caffeine(message) == "none":
            # Be explicit rather than silent: this is a real answer.
            return {
                "reply": (
                    "Everything without caffeine is on the tisane shelf: chamomile, "
                    "tulsi and mint, rooibos and orange peel, hibiscus and rose, "
                    "lemongrass and ginger. None of them come from the tea plant, so "
                    "none contain any caffeine."
                ),
                "intro": "Everything without caffeine is on the tisane shelf:",
                "source": "catalog",
                "teas": [],
            }
        return None

    # A named tea with no other signal: describe it rather than rank around it.
    if named is not None and len(teas) and teas[0].pk != named.pk:
        teas = [named] + [tea for tea in teas if tea.pk != named.pk][:2]

    intro = _intro_for(message, teas, weather_info)
    body = "\n".join(f"{index}. {tea_line(tea)}" for index, tea in enumerate(teas, 1))

    result = {
        "reply": f"{intro}\n{body}",
        "intro": intro,
        "source": "catalog",
        "teas": [
            {"name": tea.name, "url": tea.get_absolute_url(), "slug": tea.slug}
            for tea in teas
        ],
    }
    if weather_info:
        result["weather"] = {
            "source": weather_info["source"],
            "label": weather_info["label"],
        }
    return result
