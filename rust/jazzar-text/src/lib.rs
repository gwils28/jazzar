//! Primitives texte pour l'ingestion Jazzar.
//!
//! Pourquoi Rust ici : ces fonctions tournent sur chaque page de 90 ans d'archives OCRisées
//! (dizaines de millions de caractères). Elles sont pures, sans I/O, et dominées par des
//! boucles sur des chaînes : le terrain idéal pour un module natif exposé à Python via PyO3.
//! `jazzar.text` (Python) fournit la même interface en repli si le module n'est pas compilé.

use pyo3::prelude::*;
use regex::Regex;
use std::sync::OnceLock;
use unicode_normalization::UnicodeNormalization;

static RE_HYPHEN_BREAK: OnceLock<Regex> = OnceLock::new();
static RE_SOFT_BREAK: OnceLock<Regex> = OnceLock::new();
static RE_MULTI_SPACE: OnceLock<Regex> = OnceLock::new();
static RE_MULTI_NL: OnceLock<Regex> = OnceLock::new();
static RE_TOKEN: OnceLock<Regex> = OnceLock::new();

fn re_hyphen_break() -> &'static Regex {
    // "trom-\npette" -> "trompette" (césure de fin de ligne, typique des colonnes de magazine)
    RE_HYPHEN_BREAK.get_or_init(|| Regex::new(r"(\p{L})-\s*\n\s*(\p{Ll})").unwrap())
}
fn re_soft_break() -> &'static Regex {
    // Retour à la ligne simple au milieu d'une phrase -> espace
    RE_SOFT_BREAK.get_or_init(|| Regex::new(r"([^\n.!?:;\u{2014}])\n[ \t]*([\p{L}\d«(])").unwrap())
}
fn re_multi_space() -> &'static Regex {
    RE_MULTI_SPACE.get_or_init(|| Regex::new(r"[ \t\u{00A0}]{2,}").unwrap())
}
fn re_multi_nl() -> &'static Regex {
    RE_MULTI_NL.get_or_init(|| Regex::new(r"\n{3,}").unwrap())
}
fn re_token() -> &'static Regex {
    RE_TOKEN.get_or_init(|| Regex::new(r"\p{L}+|\p{N}+|[^\s\p{L}\p{N}]").unwrap())
}

/// Nettoie un texte issu de l'OCR : ligatures, césures, retours à la ligne parasites,
/// espaces multiples, caractères de contrôle. Préserve les paragraphes (double saut de ligne).
#[pyfunction]
fn clean_ocr(text: &str) -> String {
    // 1. Normalisation Unicode NFKC (ligatures ﬁ -> fi, exposants, etc.)
    let mut s: String = text.nfkc().collect();
    // 2. Caractères de contrôle et artefacts OCR courants
    s = s
        .chars()
        .filter(|c| !c.is_control() || *c == '\n' || *c == '\t')
        .collect();
    s = s.replace('\u{FEFF}', "").replace('\r', "");
    s = s.replace("\u{2018}", "'").replace("\u{2019}", "'");
    // 3. Césures de fin de ligne
    s = re_hyphen_break().replace_all(&s, "$1$2").into_owned();
    // 4. Retours à la ligne intra-phrase -> espace (préserve les vrais paragraphes)
    s = re_soft_break().replace_all(&s, "$1 $2").into_owned();
    // 5. Espaces et sauts multiples
    s = re_multi_space().replace_all(&s, " ").into_owned();
    s = re_multi_nl().replace_all(&s, "\n\n").into_owned();
    // 6. Trim par ligne
    s.lines()
        .map(|l| l.trim())
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}

/// Estimation rapide du nombre de tokens (≈ mots + ponctuation ; calibré ~1.3 token/mot
/// pour les tokenizers BPE anglais/français). Sans dépendance à un vocabulaire.
#[pyfunction]
fn estimate_tokens(text: &str) -> usize {
    let words = re_token().find_iter(text).count();
    (words as f64 * 1.3).ceil() as usize
}

/// Découpe `text` (vecteur de chars) en phrases : retourne des (start, end) contigus.
/// Fin de phrase = [.!?…] + guillemets fermants optionnels + blanc ; ou paragraphe (\n\n).
fn split_sentences(chars: &[char]) -> Vec<(usize, usize)> {
    let n = chars.len();
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < n {
        let c = chars[i];
        if matches!(c, '.' | '!' | '?' | '…') {
            let mut j = i + 1;
            while j < n && matches!(chars[j], '»' | '"' | ')' | ']' | '\'') {
                j += 1;
            }
            if j >= n || chars[j].is_whitespace() {
                while j < n && chars[j].is_whitespace() {
                    j += 1;
                }
                out.push((start, j));
                start = j;
                i = j;
                continue;
            }
        }
        if c == '\n' && i + 1 < n && chars[i + 1] == '\n' {
            let mut j = i;
            while j < n && chars[j].is_whitespace() {
                j += 1;
            }
            out.push((start, j));
            start = j;
            i = j;
            continue;
        }
        i += 1;
    }
    if start < n {
        out.push((start, n));
    }
    out
}

/// Découpe un texte en chunks d'environ `target_tokens`, avec `overlap_tokens` de recouvrement,
/// en respectant les frontières de phrases puis de paragraphes.
/// Retourne une liste de (start_char, end_char, text).
#[pyfunction]
#[pyo3(signature = (text, target_tokens = 400, overlap_tokens = 60))]
fn chunk(text: &str, target_tokens: usize, overlap_tokens: usize) -> Vec<(usize, usize, String)> {
    let chars: Vec<char> = text.chars().collect();
    let slice = |a: usize, b: usize| -> String { chars[a..b].iter().collect::<String>().trim().to_string() };
    let sentences: Vec<(usize, usize, usize)> = split_sentences(&chars)
        .into_iter()
        .filter_map(|(a, b)| {
            let s = slice(a, b);
            if s.is_empty() { None } else { Some((a, b, estimate_tokens(&s))) }
        })
        .collect();
    if sentences.is_empty() {
        return Vec::new();
    }

    let mut out = Vec::new();
    let mut i = 0usize;
    while i < sentences.len() {
        let start = sentences[i].0;
        let mut tokens = 0usize;
        let mut j = i;
        while j < sentences.len() && (tokens == 0 || tokens + sentences[j].2 <= target_tokens) {
            tokens += sentences[j].2;
            j += 1;
        }
        let end = sentences[j - 1].1;
        let s = slice(start, end);
        if !s.is_empty() {
            out.push((start, end, s));
        }
        if j >= sentences.len() {
            break;
        }
        // Recouvrement : on repart quelques phrases avant la fin du chunk courant.
        let mut back = 0usize;
        let mut k = j;
        while k > i + 1 && back + sentences[k - 1].2 <= overlap_tokens {
            back += sentences[k - 1].2;
            k -= 1;
        }
        i = k.max(i + 1);
    }
    out
}

/// Simhash 64 bits sur les shingles de mots (3-grammes). Deux textes quasi identiques
/// (même article OCRisé deux fois, doublon entre scans) ont une distance de Hamming faible.
#[pyfunction]
fn simhash(text: &str) -> u64 {
    let words: Vec<String> = re_token()
        .find_iter(text)
        .map(|m| m.as_str().to_lowercase())
        .filter(|w| w.chars().any(|c| c.is_alphanumeric()))
        .collect();
    if words.is_empty() {
        return 0;
    }
    let mut acc = [0i64; 64];
    let n = words.len();
    let window = if n >= 3 { 3 } else { n };
    for i in 0..=(n - window) {
        let shingle = words[i..i + window].join(" ");
        let h = fnv1a64(shingle.as_bytes());
        for b in 0..64 {
            if (h >> b) & 1 == 1 {
                acc[b] += 1;
            } else {
                acc[b] -= 1;
            }
        }
    }
    let mut out = 0u64;
    for b in 0..64 {
        if acc[b] > 0 {
            out |= 1 << b;
        }
    }
    out
}

/// Distance de Hamming entre deux simhash.
#[pyfunction]
fn hamming(a: u64, b: u64) -> u32 {
    (a ^ b).count_ones()
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[pymodule]
fn jazzar_text(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(clean_ocr, m)?)?;
    m.add_function(wrap_pyfunction!(estimate_tokens, m)?)?;
    m.add_function(wrap_pyfunction!(chunk, m)?)?;
    m.add_function(wrap_pyfunction!(simhash, m)?)?;
    m.add_function(wrap_pyfunction!(hamming, m)?)?;
    m.add("__backend__", "rust")?;
    Ok(())
}
