"""Optional, length-preserving Russian ё hints for speech only.

This small reviewed list deliberately excludes homographs (все/всё, берет,
осел, узнаем, передохнем, etc.). It is not a general stress/disambiguation model.
The stored book and all canonical character offsets remain unchanged.
"""
from __future__ import annotations

import re

_FORMS = """
ещё ёлка ёлки ёлке ёлку ёлкой ёлкою ёлок ёлкам ёлками ёлках
ёлочка ёлочки ёлочке ёлочку ёлочкой ёлочек ёлочкам ёлочками ёлочках
ёжик ёжика ёжику ёжиком ёжике ёжики ёжиков ёжикам ёжиками ёжиках
самолёт самолёта самолёту самолётом самолёте самолёты самолётов самолётам самолётами самолётах
вертолёт вертолёта вертолёту вертолётом вертолёте вертолёты вертолётов вертолётам вертолётами вертолётах
берёза берёзы берёзе берёзу берёзой берёзою берёз берёзам берёзами берёзах
берёзка берёзки берёзке берёзку берёзкой берёзок берёзкам берёзками берёзках
матрёшка матрёшки матрёшке матрёшку матрёшкой матрёшек матрёшкам матрёшками матрёшках
ребёнок ребёнка ребёнку ребёнком ребёнке детёныш детёныша детёнышу детёнышем детёныше
цыплёнок цыплёнка цыплёнку цыплёнком цыплёнке котёнок котёнка котёнку котёнком котёнке
утёнок утёнка утёнку утёнком утёнке телёнок телёнка телёнку телёнком телёнке
трёх четырёх трём четырём трёхсот четырёхсот трёхмерный четырёхмерный
""".split()
_YO = {word.replace("ё", "е"): word for word in _FORMS}
_WORD = re.compile(r"[А-Яа-яЁё]+")


def russian_yo(text: str) -> tuple[str, int]:
    replacements = 0
    def replace(match: re.Match) -> str:
        nonlocal replacements
        original = match.group()
        corrected = _YO.get(original.lower())
        if corrected is None:
            return original
        replacements += sum(a.lower() != b for a, b in zip(original, corrected))
        return "".join(new.upper() if old.isupper() else new for old, new in zip(original, corrected))
    return _WORD.sub(replace, text), replacements
