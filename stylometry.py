import re
import statistics
from collections import Counter

def sentence_tokenize(text):
    # naive split on sentence-ending punctuation
    sents = re.split(r'[.!?]+\s*', text.strip())
    sents = [s for s in sents if s]
    return sents

def tokenize_words(text):
    return re.findall(r"\b\w+\b", text.lower())

def type_token_ratio(words):
    if not words:
        return 0.0
    return len(set(words)) / len(words)

def compute_stylometry_score(text):
    """Return [0,1] score where higher = more likely AI-generated."""
    words = tokenize_words(text)
    sents = sentence_tokenize(text)
    if not words or not sents:
        return 0.5

    avg_sent_len = sum(len(tokenize_words(s)) for s in sents) / len(sents)
    sent_lens = [len(tokenize_words(s)) for s in sents]
    sent_var = statistics.pvariance(sent_lens) if len(sent_lens) > 1 else 0.0
    ttr = type_token_ratio(words)
    punct_density = len(re.findall(r"[.,;:\-()\"]", text)) / max(1, len(words))

    # AI tends to have: low variance, low TTR, normalized punctuation
    score = 0.0
    score += (1.0 - min(sent_var / (avg_sent_len+1), 1.0)) * 0.4
    score += (1.0 - ttr) * 0.4
    score += (1.0 - min(punct_density * 5.0, 1.0)) * 0.2

    return max(0.0, min(1.0, round(score, 4)))
