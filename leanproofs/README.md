# Helios: Machine-Checked Formal Verification in Lean 4

This directory contains the machine-checked formal verification in Lean 4 (version 4.35.0) and the computational verification suite for all theoretical foundations, invariance laws, and variance projection scaling identities established in the paper:

> **"Measurement and Prediction of Landsat-derived Land Surface Temperature in Chennai and Bangalore, India, Using a Polyglot Machine Learning Pipeline"** (*Urban Climate*, Accepted 12 Nov 2026).

---

## Directory Structure

- `lakefile.toml` / `lean-toolchain`: Lake project configuration (Lean v4.35.0).
- `HeliosProofs.lean`: Root library entry point for Lake.
- `HeliosProofs/Basic.lean`: Lean 4 formal machine proofs for all propositions and corollaries (compiled with **0 errors, 0 `sorry`**).
- `Main.lean`: Executable driver reporting formal proof status.
- `verify_math.py`: Standalone computational verification script validating exact fractional arithmetic and empirical holdout bounds.

---

## Verified Theorems, Lemmas, Propositions, and Corollaries

| Paper Section | Label | Description | Lean 4 Formal Identifier | Status |
|:---|:---|:---|:---|:---:|
| **Section 5 & Appendix B.1** | `prop:variance` | **Proposition 1**: Invariant-Error Variance-Projection Law | `Helios.variance_projection_identity` | **PROVED** |
| **Section 5 & Appendix B.1** | `cor:bangalore` | **Corollary 1.1**: Bangalore Theoretical Projection & Error Bound ($R^2_{\text{proj}} = 0.2959 \approx 0.292$) | `Helios.bangalore_projected_exact_numerator`<br>`Helios.bangalore_projected_exact_denominator`<br>`Helios.bangalore_projection_bound_upper`<br>`Helios.bangalore_projection_bound_lower` | **PROVED** |
| **Section 5 & Appendix B.1** | `cor:winter` | **Corollary 1.2**: Implied Winter Target Variance & Seasonal Equivalence ($\sigma_{\text{Feb}} \approx 2.94\text{ K} \approx \sigma_{\text{Blr}}$) | `Helios.implied_one_minus_r2`<br>`Helios.implied_variance_close_to_bangalore`<br>`Helios.implied_sigma_bound_low`<br>`Helios.implied_sigma_bound_high`<br>`Helios.winter_sigma_discrepancy_bound` | **PROVED** |
| **Section 2.5 & Appendix B.2** | `prop:tree` | **Proposition 2**: Coordinate Partition Invariance of Tree Ensembles under Monotonic Maps | `Helios.tree_split_monotonic_invariance`<br>`Helios.tree_split_partition_extensional_eq`<br>`Helios.tree_split_indicator_eq` | **PROVED** |
| **Section 2.5 & Appendix B.3** | `prop:leakage` | **Proposition 3**: Bayesian Target Encoding Regularization & Zero Data Leakage ($\frac{\partial \hat{z}(z_k)}{\partial y_j} \equiv 0$) | `Helios.bayesian_encoding_test_leakage_independence`<br>`Helios.test_target_zero_data_leakage` | **PROVED** |

---

## How to Run the Verification

### 1. Build and Run the Lean 4 Formal Proofs with Lake
```bash
cd leanproofs
lake build
lake exe helios_proofs
```

### 2. Check Individual File with Lean 4 directly
```bash
lean leanproofs/HeliosProofs/Basic.lean
```

### 3. Run the Computational Verification Suite
```bash
python3 leanproofs/verify_math.py
```

