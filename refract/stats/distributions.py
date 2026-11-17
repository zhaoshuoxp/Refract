"""Distributions behind the multiple-comparison tests, matched to Prism.

* ptukey / qtukey: studentized range. Prism agrees with the Copenhaver &
  Holland (1988) Gauss-Legendre algorithm (as in R's ptukey.c, AS 190 lineage)
  to ~1e-14 absolute; scipy's studentized_range differs by up to 1e-3 relative
  in the far tail. Upper-tail P is 1 - cdf, as Prism's is.
* dunnett_sf: two-sided Dunnett, P(max |T_i| >= c) for the product
  correlation rho_ij = lam_i lam_j, by nested quadrature (Prism agrees to
  ~1e-15 absolute; scipy.stats.dunnett is randomised).
* smm_sf: studentized maximum modulus (Dunnett T3) of m independent t's.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from scipy import integrate, optimize, special

_XLEG = (0.981560634246719250690549090149, 0.904117256370474856678465866119, 0.769902674194304687036893833213,
         0.587317954286617447296702418941, 0.367831498998180193752691536644, 0.125233408511468915472441369464)
_ALEG = (0.047175336386511827194615961485, 0.106939325995318430960254718194, 0.160078328543346226334652529543,
         0.203167426723065921749064455810, 0.233492536538354808760849898925, 0.249147045813402785000562436043)
_XLEGQ = (0.989400934991649932596154173450, 0.944575023073232576077988415535, 0.865631202387831743880467897712,
          0.755404408355003033895101194847, 0.617876244402643748446671764049, 0.458016777657227386342419442984,
          0.281603550779258913230460501460, 0.950125098376374401853193354250e-1)
_ALEGQ = (0.271524594117540948517805724560e-1, 0.622535239386478928628438369944e-1, 0.951585116824927848099251076022e-1,
          0.124628971255533872052476282192, 0.149595988816576732081501730547, 0.169156519395002538189312079030,
          0.182603415044923588866763667969, 0.189450610455068496285396723208)
_SQRT_2PI = math.sqrt(2 * math.pi)


def _wprob(w: float, rr: float, cc: float) -> float:
    """P(range of cc standard normals <= w), raised to rr."""
    qsqz = w * 0.5
    if qsqz >= 8.0:
        return 1.0
    pr_w = 2 * special.ndtr(qsqz) - 1
    pr_w = pr_w ** cc if pr_w >= math.exp(-50.0 / cc) else 0.0
    wincr = 2 if w > 3.0 else 3
    blb = qsqz
    binc = (8.0 - qsqz) / wincr
    bub = blb + binc
    einsum = 0.0
    cc1 = cc - 1.0
    for _ in range(wincr):
        elsum = 0.0
        a = 0.5 * (bub + blb)
        b = 0.5 * (bub - blb)
        for jj in range(1, 13):
            if jj > 6:
                j = 12 - jj + 1
                xx = _XLEG[j - 1]
            else:
                j = jj
                xx = -_XLEG[j - 1]
            ac = a + b * xx
            qexpo = ac * ac
            if qexpo > 60.0:
                break
            rinsum = special.ndtr(ac) - special.ndtr(ac - w)
            if rinsum >= math.exp(-30.0 / cc1):
                elsum += _ALEG[j - 1] * math.exp(-0.5 * qexpo) * rinsum ** cc1
        einsum += elsum * (2.0 * b * cc / _SQRT_2PI)
        blb = bub
        bub += binc
    pr_w += einsum
    if pr_w <= math.exp(-30.0 / rr):
        return 0.0
    return min(1.0, pr_w ** rr)


def ptukey(q: float, k: int, df: float) -> float:
    """CDF of the studentized range of k means with df error degrees of freedom."""
    if q <= 0:
        return 0.0
    if not math.isfinite(q):
        return 1.0
    if df > 25000:
        return _wprob(q, 1.0, k)
    f2 = df * 0.5
    f2lf = f2 * math.log(df) - df * math.log(2) - special.gammaln(f2)
    f21 = f2 - 1.0
    ff4 = df * 0.25
    ulen = 1.0 if df <= 100 else 0.5 if df <= 800 else 0.25 if df <= 5000 else 0.125
    f2lf += math.log(ulen)
    ans = 0.0
    for i in range(1, 51):
        otsum = 0.0
        twa1 = (2 * i - 1) * ulen
        for jj in range(1, 17):
            if jj > 8:
                j = jj - 9
                u = twa1 + _XLEGQ[j] * ulen
                t1 = f2lf + f21 * math.log(u) - u * ff4
            else:
                j = jj - 1
                u = twa1 - _XLEGQ[j] * ulen
                t1 = f2lf + f21 * math.log(u) + (_XLEGQ[j] * ulen - twa1) * ff4
            if t1 >= -30.0:
                otsum += _wprob(q * math.sqrt(u * 0.5), 1.0, k) * _ALEGQ[j] * math.exp(t1)
        if i * ulen >= 1.0 and otsum <= 1e-14:
            break
        ans += otsum
    return min(1.0, ans)


def tukey_sf(q: float, k: int, df: float) -> float:
    return 1.0 - ptukey(q, k, df)


@lru_cache(maxsize=4096)
def qtukey(p: float, k: int, df: float) -> float:
    """Inverse of ptukey (critical q for confidence p)."""
    return float(optimize.brentq(lambda q: ptukey(q, k, df) - p, 1e-8, 200.0, xtol=1e-15, rtol=1e-15))


# ------------------------------------------------------------------ Dunnett
_GL_Z, _GL_W = np.polynomial.legendre.leggauss(400)
_Z = _GL_Z * 12.0
_ZW = _GL_W * 12.0 * np.exp(-_Z * _Z / 2) / _SQRT_2PI


def _dunnett_given_s(cs: float, lam: np.ndarray, sig: np.ndarray) -> float:
    """P(max |Z_i| >= cs) for Z_i = lam_i Z0 + sig_i e_i (standard normals)."""
    a = (cs + np.outer(_Z, lam)) / sig
    b = (np.outer(_Z, lam) - cs) / sig
    u = np.minimum(special.ndtr(-a) + special.ndtr(b), 1.0)
    return float(np.dot(_ZW, -np.expm1(np.log1p(-u).sum(axis=1))))


def _chi_scaled_pdf(s: float, df: float) -> float:
    """Density of s = chi_df / sqrt(df)."""
    if s <= 0:
        return 0.0
    return math.exp(math.log(2) + (df / 2) * math.log(df / 2) - special.gammaln(df / 2)
                    + (df - 1) * math.log(s) - df * s * s / 2)


def dunnett_sf(c: float, lam, df: float) -> float:
    """Two-sided Dunnett P value for |t| = c; lam_i = sqrt(n_i / (n_i + n_0))."""
    lam = np.asarray(lam, float)
    sig = np.sqrt(1 - lam ** 2)
    if not math.isfinite(df):
        return _dunnett_given_s(c, lam, sig)
    val, _ = integrate.quad(lambda s: _chi_scaled_pdf(s, df) * _dunnett_given_s(c * s, lam, sig), 0, np.inf,
                            epsabs=1e-17, epsrel=1e-12, limit=200)
    return min(1.0, max(0.0, val))


def dunnett_crit(alpha: float, lam, df: float) -> float:
    lam = tuple(float(x) for x in lam)
    return _dunnett_crit(alpha, lam, float(df))


@lru_cache(maxsize=1024)
def _dunnett_crit(alpha: float, lam: tuple, df: float) -> float:
    return float(optimize.brentq(lambda c: dunnett_sf(c, lam, df) - alpha, 1e-6, 100.0, xtol=1e-14, rtol=1e-15))


# ------------------------------------------- studentized maximum modulus (T3)
def smm_cdf(c: float, m: int, df: float) -> float:
    """P(max of m independent |t_df| <= c)."""

    def body(cs: float) -> float:
        return (1 - 2 * special.ndtr(-cs)) ** m

    if not math.isfinite(df):
        return body(c)
    val, _ = integrate.quad(lambda s: _chi_scaled_pdf(s, df) * body(c * s), 0, np.inf,
                            epsabs=0, epsrel=1e-13, limit=200)
    return min(1.0, max(0.0, val))


def smm_sf(c: float, m: int, df: float) -> float:
    """1 - smm_cdf, as Prism computes it: exactly 1 when the cdf underflows
    (Prism then reports the CI as undefined). Prism's own tail differs from
    an accurate tail by up to ~1e-10 absolute for P near 1e-9."""
    return 1.0 - smm_cdf(c, m, df)


@lru_cache(maxsize=1024)
def smm_crit(alpha: float, m: int, df: float) -> float:
    return float(optimize.brentq(lambda c: smm_sf(c, m, df) - alpha, 1e-6, 1000.0, xtol=1e-14, rtol=1e-15))
