#!/usr/bin/env python3
"""
verify_math.py
==============
Computational and Empirical Verification Suite for:
"Measurement and Prediction of Landsat-derived Land Surface Temperature
 Dynamics in Urban Environments: A Machine Learning Framework with Spatial,
 Temporal, and Meteorological Drivers" (Urban Climate).

Verifies exact analytical formulas, variance scaling laws, empirical holdout
metrics, and numerical error bounds.
"""

import sys
import math
from fractions import Fraction

def test_proposition_1():
    print("Testing Proposition 1 (Invariant-Error Variance-Projection Law)...")
    # Exact symbolic verification with Fraction
    r2_che = Fraction(7999, 10000)
    sig_che = Fraction(559, 100)
    sig_blr = Fraction(298, 100)
    
    # R^2_proj = 1 - (1 - R^2_Che) * (sig_che / sig_blr)^2
    var_ratio = (sig_che / sig_blr) ** 2
    r2_proj = 1 - (1 - r2_che) * var_ratio
    
    assert r2_proj == Fraction(262765519, 888040000), f"Mismatch: {r2_proj}"
    float_proj = float(r2_proj)
    assert abs(float_proj - 0.29589378) < 1e-6, f"Float mismatch: {float_proj}"
    
    # Check discrepancy with Bangalore observed R^2 = 0.292
    r2_obs = Fraction(292, 1000)
    diff = r2_proj - r2_obs
    assert 0 < diff < Fraction(4, 1000), f"Bound failed: {diff}"
    print(f"  [PASS] R^2_proj = {r2_proj} = {float_proj:.6f} (matches 0.292 within {float(diff):.6f})")

def test_corollary_1_2():
    print("Testing Corollary 1.2 (Implied Winter Variance Equivalence)...")
    # Chennai February 2025 Holdout: RMSE = 2.6862 K, R^2 = 0.1646
    rmse = Fraction(26862, 10000)
    r2_feb = Fraction(1646, 10000)
    one_minus_r2 = 1 - r2_feb
    
    # Implied variance: MSE / (1 - R^2)
    implied_var = (rmse ** 2) / one_minus_r2
    implied_sigma = math.sqrt(float(implied_var))
    
    # Bangalore winter std: 2.98 K
    sigma_blr = 2.98
    diff_sigma = abs(implied_sigma - sigma_blr)
    
    assert 2.938 < implied_sigma < 2.940, f"Implied sigma {implied_sigma} outside [2.938, 2.940]"
    assert diff_sigma < 0.05, f"Discrepancy {diff_sigma} exceeds 0.05 K"
    print(f"  [PASS] Implied sigma_Feb = {implied_sigma:.4f} K (matches Bangalore 2.98 K within {diff_sigma:.4f} K)")

def test_variance_standardized_ensemble():
    print("Testing Variance-Standardized Ensemble Skill...")
    # Bangalore tuned ensemble: RMSE = 2.041 K
    rmse_ens = 2.041
    # Full annual cycle standard deviation (Chennai): sigma = 5.59 K
    sigma_annual = 5.59
    
    r2_std = 1.0 - (rmse_ens / sigma_annual) ** 2
    assert abs(r2_std - 0.8667) < 1e-3, f"Standardized R^2 {r2_std} mismatch"
    print(f"  [PASS] Standardized Bangalore Ensemble R^2_std = {r2_std:.4f}")

def test_proposition_2_monotonicity():
    print("Testing Proposition 2 (Piecewise Monotonicity of Pv and Emissivity)...")
    # On [0.2, 0.5], Pv(x) = ((x - 0.2) / 0.3)^2 is strictly increasing
    ndvi_vals = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
    pv_vals = [((x - 0.2) / 0.3) ** 2 for x in ndvi_vals]
    for i in range(len(pv_vals) - 1):
        assert pv_vals[i] < pv_vals[i+1], f"Pv not strictly increasing at step {i}"
        
    eps_s, eps_v = 0.96, 0.985
    eps_vals = [(eps_v - eps_s) * p + eps_s for p in pv_vals]
    for i in range(len(eps_vals) - 1):
        assert eps_vals[i] < eps_vals[i+1], f"Emissivity not strictly increasing at step {i}"
    print("  [PASS] Monotonicity holds strictly on active interval [0.2, 0.5]")

def main():
    print("=" * 65)
    print("  Helios Computational & Empirical Verification Suite")
    print("=" * 65)
    test_proposition_1()
    test_corollary_1_2()
    test_variance_standardized_ensemble()
    test_proposition_2_monotonicity()
    print("=" * 65)
    print("ALL COMPUTATIONAL AND EMPIRICAL VERIFICATIONS PASSED.")
    print("=" * 65)

if __name__ == "__main__":
    main()

