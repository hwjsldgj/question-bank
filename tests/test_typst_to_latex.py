# -*- coding: utf-8 -*-
"""typst_to_latex 回归测试。"""
import pytest
from app.infrastructure.exporters.md_exporter import typst_to_latex


def _u(*codes):
    return "".join(chr(c) for c in codes)


CASES = [
    (r"$frac(a,b)$", r"$\frac{a}{b}$"),
    (r"$frac((a^2-b^2)|y|, 2a b^2)$", r"$\frac{(a^2-b^2)|y|}{2a b^2}$"),
    (r"$x in RR$", r"$x \in \mathbb{R}$"),
    (r"$4 in.not A$", r"$4 \notin A$"),
    (r"$m subset.not \alpha$", r"$m \not\subset \alpha$"),
    (r"$A inter B$", r"$A \cap B$"),
    (r"$A union B$", r"$A \cup B$"),
    (r"$complement_A B$", r"$\complement _A B$"),
    (r"$not p or q$", r"$\lnot p \lor q$"),
    (r"$p and not q$", r"$p \land \lnot q$"),
    (r"$therefore$", r"$\therefore$"),
    (r"$becauseB$", r"$\because B$"),
    (r"$cos lr(\langle a-c, b-c \rangle)$", r"$\cos\langle a-c, b-c \rangle$"),
    (r"$x=2,\quad y=3$", r"$x=2,\quad y=3$"),
    (r"$x=2,quadx^2$", r"$x=2,\quad x^2$"),
    (r"$x=2,\\\quad y=3$", r"$x=2,\quad y=3$"),
    (r"$n \in \mathbb{N}^*$", r"$n \in \mathbb{N}^{\ast }$"),
    (r"$T_(r+1)=C_8^r$", r"$T_{r+1}=C_8^r$"),
    (r"$x^(1/3)$", r"$x^{1/3}$"),
    (r"$sum_(i=1)^16 x_i$", r"$\sum _{i=1}^{16} x_i$"),
    (r"$mat(delim: |, 1, 2; 3, 4)$", r"$\begin{vmatrix}1 & 2 \\ 3 & 4\end{vmatrix}$"),
    (r"$cases(x\&\quad y\ge 0, -x\&\quad y<0)$", r"$\begin{cases}x & y\ge 0 \\ -x & y<0\end{cases}$"),
    (r"$x " + _u(0x2208) + " " + _u(0x211D) + "$", r"$x \in \mathbb{R}$"),
    (r"$" + _u(0x03C0) + " " + _u(0x2264) + " " + _u(0x221E) + "$", r"$\pi \le \infty$"),
    (r"$a_1, \cdot s.c, a_n$", r"$a_1, \cdots, a_n$"),
    (r"$sqrt(x)$", r"$\sqrt{x}$"),
    (r"$root(3, x)$", r"$\sqrt[3]{x}$"),
    (r"$abs(x)$", r"$\left|x\right|$"),
    (r"$arrow(a)$", r"$\vec{a}$"),
    (r"$sin x + cos x$", r"$\sin x + \cos x$"),
]


@pytest.mark.parametrize("src,expected", CASES, ids=[c[0][:30] for c in CASES])
def test_typst_to_latex(src, expected):
    assert typst_to_latex(src) == expected


def test_empty_input():
    assert typst_to_latex("") == ""
    assert typst_to_latex(None) is None