from __future__ import annotations

import re


SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUBSCRIPT = str.maketrans("0123456789+-=()aeiox", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓ")

LATEX_SYMBOLS = {
    r"\times": "×",
    r"\cdot": "·",
    r"\pm": "±",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\rightarrow": "→",
    r"\leftarrow": "←",
    r"\infty": "∞",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\sigma": "σ",
    r"\theta": "θ",
}


def _script_value(value: str, table: dict[int, str], marker: str) -> str:
    translated = value.translate(table)
    if translated != value or all(character in table for character in map(ord, value)):
        return translated
    return f"{marker}({value})"


def _plain_formula(expression: str) -> str:
    value = expression.strip()
    value = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", value)
    value = re.sub(
        r"\\(?:text|textrm|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|mathcal)\{([^{}]*)\}",
        r"\1",
        value,
    )
    for latex, symbol in LATEX_SYMBOLS.items():
        value = value.replace(latex, symbol)
    value = re.sub(
        r"\^\{([^{}]+)\}",
        lambda match: _script_value(match.group(1), SUPERSCRIPT, "^"),
        value,
    )
    value = re.sub(
        r"\^([0-9n])",
        lambda match: _script_value(match.group(1), SUPERSCRIPT, "^"),
        value,
    )
    value = re.sub(
        r"_\{([^{}]+)\}",
        lambda match: _script_value(match.group(1), SUBSCRIPT, "_"),
        value,
    )
    value = re.sub(
        r"_([0-9aeiox])",
        lambda match: _script_value(match.group(1), SUBSCRIPT, "_"),
        value,
    )
    value = value.replace(r"\,", " ").replace(r"\ ", " ")
    value = value.replace(r"\left", "").replace(r"\right", "")
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", value).strip()


def format_latex_for_feishu(text: object) -> str:
    """Convert common LaTeX fragments into readable Feishu card text."""
    value = str(text or "")
    value = re.sub(
        r"\$\$(.+?)\$\$",
        lambda match: "\n" + _plain_formula(match.group(1)) + "\n",
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"\\\[(.+?)\\\]",
        lambda match: "\n" + _plain_formula(match.group(1)) + "\n",
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"\\\((.+?)\\\)",
        lambda match: _plain_formula(match.group(1)),
        value,
        flags=re.DOTALL,
    )
    value = re.sub(
        r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
        lambda match: _plain_formula(match.group(1)),
        value,
        flags=re.DOTALL,
    )
    return re.sub(r"\n{3,}", "\n\n", value).strip()
