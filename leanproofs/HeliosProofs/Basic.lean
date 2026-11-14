/-
  HeliosProofs/Basic.lean
  =============================================================================
  Formal Machine-Checked Mathematical Foundations for:
  "Measurement and Prediction of Landsat-derived Land Surface Temperature
   Dynamics in Urban Environments: A Machine Learning Framework with Spatial,
   Temporal, and Meteorological Drivers" (Urban Climate).

  Machine-verified using the Lean 4 interactive theorem prover (v4.35.0).
  Contains formal, machine-checked proofs for:
    - Proposition 1: Invariant-Error Variance-Projection Law
    - Corollary 1.1: Bangalore Theoretical Projection Law & Error Bound
    - Corollary 1.2: Implied Winter Variance & Seasonal Discrepancy Bound
    - Proposition 2: Coordinate Partition Invariance of Tree Ensembles under
                     Monotonic Transformations
    - Proposition 3: Bayesian Smoothed Target Encoding Regularization and
                     Exact Data Leakage Independence
  =============================================================================
-/

import Std

set_option linter.unusedVariables false

namespace Helios

/-! # SECTION 1: Proposition 1 - Invariant-Error Variance-Projection Law -/

/-- Definition of R-squared in terms of Mean Squared Error (MSE) and variance -/
def r_squared (mse var : Rat) : Rat := 1 - (mse / var)

/-- Auxiliary arithmetic lemma: 1 - (1 - x) = x for any rational x -/
theorem rat_sub_sub_self (x : Rat) : 1 - (1 - x) = x := by
  have h1 : 1 - x + x = 1 := Rat.sub_add_cancel
  have h2 : 1 - (1 - x) = (1 - x + x) - (1 - x) := by rw [h1]
  rw [h2]
  rw [Rat.add_comm (1 - x) x]
  exact Rat.add_sub_cancel

/--
  Proposition 1: If predictive mean squared error is invariant across two
  evaluation domains A and B (MSE_A = MSE_B), the achievable R^2 in domain B
  is uniquely and analytically determined by domain A's R^2 scaled by the
  ratio of domain variances:
    R^2_B = 1 - (1 - R^2_A) * (Var_A / Var_B)
-/
theorem variance_projection_identity
    (mse_A mse_B var_A var_B : Rat)
    (h_var_A : var_A ≠ 0)
    (h_var_B : var_B ≠ 0)
    (h_mse : mse_B = mse_A) :
    let R2_A := r_squared mse_A var_A
    let R2_B := r_squared mse_B var_B
    R2_B = 1 - (1 - R2_A) * (var_A / var_B) := by
  intro R2_A R2_B
  dsimp [R2_A, R2_B, r_squared]
  rw [h_mse]
  have h1 : 1 - (1 - mse_A / var_A) = mse_A / var_A := rat_sub_sub_self (mse_A / var_A)
  rw [h1]
  have h2 : (mse_A / var_A) * (var_A / var_B) = mse_A / var_B := by
    rw [Rat.div_def, Rat.div_def, Rat.div_def]
    rw [Rat.mul_assoc mse_A var_A⁻¹ (var_A * var_B⁻¹)]
    rw [← Rat.mul_assoc var_A⁻¹ var_A var_B⁻¹]
    rw [Rat.inv_mul_cancel var_A h_var_A]
    rw [Rat.one_mul]
  rw [h2]


/-! # SECTION 2: Corollary 1.1 - Bangalore Theoretical Projection -/

-- Reported empirical parameters from the Chennai full annual cycle:
-- R^2_Che = 0.7999 = 7999 / 10000
-- sigma_Che = 5.59 K => Var_Che = (559 / 100)^2
def r2_chennai : Rat := 7999 / 10000
def sigma_chennai : Rat := 559 / 100

-- Bangalore winter holdout standard deviation:
-- sigma_Blr = 2.98 K => Var_Blr = (298 / 100)^2
def sigma_bangalore : Rat := 298 / 100

-- Bangalore observed single-model test R^2: 0.292
def r2_bangalore_observed : Rat := 292 / 1000

/-- The theoretical projected R^2 under invariant physical accuracy (RMSE = 2.50 K) -/
def r2_projected : Rat :=
  1 - (1 - r2_chennai) * ((sigma_chennai / sigma_bangalore) * (sigma_chennai / sigma_bangalore))

/-- Exact rational evaluation: R^2_proj = 262765519 / 888040000 ≈ 0.29589... -/
theorem bangalore_projected_exact_numerator : r2_projected.num = 262765519 := by
  native_decide

theorem bangalore_projected_exact_denominator : r2_projected.den = 888040000 := by
  native_decide

/-- The theoretical projection matches observed Bangalore R^2 within 0.004 (0.4%) -/
theorem bangalore_projection_bound_upper :
    r2_projected - r2_bangalore_observed < 4 / 1000 := by
  native_decide

theorem bangalore_projection_bound_lower :
    r2_projected > r2_bangalore_observed := by
  native_decide


/-! # SECTION 3: Corollary 1.2 - Implied Winter Variance & Equivalence -/

/-- General identity: 1 - R^2 = MSE / Var -/
theorem implied_one_minus_r2
    (mse var : Rat) :
    1 - r_squared mse var = mse / var := by
  dsimp [r_squared]
  exact rat_sub_sub_self (mse / var)

-- Chennai February 2025 holdout empirical values:
-- RMSE = 2.6862 K => MSE = 2.6862^2 = 7.21566844
-- R^2 = 0.1646 => 1 - R^2 = 0.8354
def chennai_feb_mse : Rat := (26862 : Rat) * 26862 / (10000 * 10000)
def chennai_feb_one_minus_r2 : Rat := (8354 : Rat) / 10000

-- Implied February thermal variance: sigma_Feb^2 = MSE / (1 - R^2)
def implied_chennai_feb_var : Rat :=
  chennai_feb_mse / chennai_feb_one_minus_r2

-- Bangalore winter variance: 2.98^2 = 8.8804
def bangalore_winter_var : Rat := (298 : Rat) * 298 / (100 * 100)

/-- Implied February variance is within 0.25 K^2 of Bangalore winter variance -/
theorem implied_variance_close_to_bangalore :
    bangalore_winter_var - implied_chennai_feb_var < (25 : Rat) / 100 ∧
    bangalore_winter_var - implied_chennai_feb_var > 0 := by
  native_decide

/-- Implied standard deviation sigma_Feb is strictly bounded within [2.938 K, 2.940 K],
    confirming the reported value sigma_Feb = 2.939 K -/
theorem implied_sigma_bound_low :
    implied_chennai_feb_var > (2938 : Rat) * 2938 / (1000 * 1000) := by
  native_decide

theorem implied_sigma_bound_high :
    implied_chennai_feb_var < (2940 : Rat) * 2940 / (1000 * 1000) := by
  native_decide

/-- Difference between Chennai winter sigma and Bangalore winter sigma is < 0.05 K -/
theorem winter_sigma_discrepancy_bound :
    implied_chennai_feb_var > (2980 - 50 : Rat) * (2980 - 50) / (1000 * 1000) := by
  native_decide


/-! # SECTION 4: Proposition 2 - Coordinate Partition Invariance of Tree Ensembles -/

/-- Decision tree binary partition predicate on feature x at threshold t -/
def split_partition (x : Nat → Rat) (t : Rat) : Nat → Prop :=
  fun i => x i ≤ t

/--
  Proposition 2: For any strictly order-preserving coordinate transformation g,
  the binary decision tree sample partition induced by threshold t on x
  is identical to the partition induced by threshold g(t) on g(x).
-/
theorem tree_split_monotonic_invariance
    (g : Rat → Rat)
    (h_mono : ∀ a b, a ≤ b ↔ g a ≤ g b)
    (x : Nat → Rat)
    (t : Rat)
    (i : Nat) :
    split_partition x t i ↔ split_partition (fun j => g (x j)) (g t) i := by
  dsimp [split_partition]
  exact h_mono (x i) t

/-- Extensional equality of the decision partition sets -/
theorem tree_split_partition_extensional_eq
    (g : Rat → Rat)
    (h_mono : ∀ a b, a ≤ b ↔ g a ≤ g b)
    (x : Nat → Rat)
    (t : Rat) :
    split_partition x t = split_partition (fun j => g (x j)) (g t) := by
  funext i
  apply propext
  exact tree_split_monotonic_invariance g h_mono x t i

/-- Binary split indicator function -/
def indicator (P : Prop) [Decidable P] : Nat :=
  if P then 1 else 0

/-- Decision tree split indicator invariance under order-preserving transformation -/
theorem tree_split_indicator_eq
    (g : Rat → Rat)
    (h_mono : ∀ a b, a ≤ b ↔ g a ≤ g b)
    (x : Nat → Rat)
    (t : Rat)
    (i : Nat)
    [d1 : Decidable (split_partition x t i)]
    [d2 : Decidable (split_partition (fun j => g (x j)) (g t) i)] :
    indicator (split_partition x t i) = indicator (split_partition (fun j => g (x j)) (g t) i) := by
  dsimp [indicator]
  have h_iff := tree_split_monotonic_invariance g h_mono x t i
  cases d1 with
  | isFalse hf =>
    have hf2 : ¬ split_partition (fun j => g (x j)) (g t) i := fun ht => hf (h_iff.mpr ht)
    cases d2 with
    | isFalse _ => rfl
    | isTrue ht => contradiction
  | isTrue ht =>
    have ht2 : split_partition (fun j => g (x j)) (g t) i := h_iff.mp ht
    cases d2 with
    | isFalse _ => contradiction
    | isTrue _ => rfl


/-! # SECTION 5: Proposition 3 - Bayesian Smoothed Target Encoding Leakage Independence -/

/-- A training/test dataset partition on index space Fin N -/
structure DatasetSplit (N : Nat) where
  train : List (Fin N)
  test : List (Fin N)
  disjoint : ∀ i, i ∈ train → i ∉ test

/-- Sum of targets for a given category c strictly in the training partition -/
def category_target_sum {N : Nat} (train : List (Fin N)) (z : Fin N → Nat) (y : Fin N → Rat) (c : Nat) : Rat :=
  train.foldl (fun acc i => if z i = c then acc + y i else acc) 0

/-- Count of occurrences for a given category c in the training partition -/
def category_count {N : Nat} (train : List (Fin N)) (z : Fin N → Nat) (c : Nat) : Nat :=
  train.foldl (fun acc i => if z i = c then acc + 1 else acc) 0

/-- Global sum of targets strictly in the training partition -/
def global_target_sum {N : Nat} (train : List (Fin N)) (y : Fin N → Rat) : Rat :=
  train.foldl (fun acc i => acc + y i) 0

/--
  Bayesian smoothed target encoding formula:
    z_hat(c) = (sum_{train, z=c} y_i + m * mu_train) / (n_c + m)
    where mu_train = (sum_{train} y_i) / |train|
-/
def bayesian_target_encoding {N : Nat}
    (train : List (Fin N))
    (z : Fin N → Nat)
    (y : Fin N → Rat)
    (m : Rat)
    (c : Nat) : Rat :=
  let n_c : Rat := (category_count train z c : Rat)
  let sum_c := category_target_sum train z y c
  let n_train : Rat := (train.length : Rat)
  let mu_train := global_target_sum train y / n_train
  (sum_c + m * mu_train) / (n_c + m)

/-- Auxiliary lemma: foldl equality over lists under point-wise equivalence on elements -/
theorem foldl_ext_eq {N : Nat} (l : List (Fin N)) (f g : Rat → Fin N → Rat) (h_eq : ∀ acc i, i ∈ l → f acc i = g acc i) :
    l.foldl f 0 = l.foldl g 0 := by
  have gen : ∀ acc, l.foldl f acc = l.foldl g acc := by
    induction l with
    | nil => intro acc; rfl
    | cons hd tl ih =>
      intro acc
      dsimp [List.foldl]
      have h_hd : f acc hd = g acc hd := h_eq acc hd (List.Mem.head tl)
      rw [h_hd]
      apply ih
      intro a i hi
      exact h_eq a i (List.Mem.tail hd hi)
  exact gen 0

/--
  Proposition 3: For any two target assignments y and y' that coincide on the
  training set (train), the Bayesian target encoding for ANY category c is
  IDENTICALLY equal.
-/
theorem bayesian_encoding_test_leakage_independence
    {N : Nat}
    (split : DatasetSplit N)
    (z : Fin N → Nat)
    (y y' : Fin N → Rat)
    (m : Rat)
    (h_train_identical : ∀ i, i ∈ split.train → y i = y' i)
    (c : Nat) :
    bayesian_target_encoding split.train z y m c = bayesian_target_encoding split.train z y' m c := by
  dsimp [bayesian_target_encoding]
  have h_cat_sum : category_target_sum split.train z y c = category_target_sum split.train z y' c := by
    dsimp [category_target_sum]
    apply foldl_ext_eq
    intro acc i hi
    have h_yi := h_train_identical i hi
    by_cases hz : z i = c <;> simp [hz, h_yi]
  have h_glob_sum : global_target_sum split.train y = global_target_sum split.train y' := by
    dsimp [global_target_sum]
    apply foldl_ext_eq
    intro acc i hi
    have h_yi := h_train_identical i hi
    simp [h_yi]
  rw [h_cat_sum, h_glob_sum]

/--
  Corollary 3.1 (Exact Zero Data Leakage):
  Modifying any test target y_j (j ∈ test) has EXACTLY ZERO effect on the
  encoded category values evaluated on any test instance k ∈ test.
  (Formally: ∂ z_hat(z_k) / ∂ y_j ≡ 0).
-/
theorem test_target_zero_data_leakage
    {N : Nat}
    (split : DatasetSplit N)
    (z : Fin N → Nat)
    (y : Fin N → Rat)
    (j : Fin N)
    (hj : j ∈ split.test)
    (new_test_target : Rat)
    (m : Rat)
    (k : Fin N)
    (hk : k ∈ split.test) :
    let y_perturbed := fun i => if i = j then new_test_target else y i
    bayesian_target_encoding split.train z y_perturbed m (z k) =
    bayesian_target_encoding split.train z y m (z k) := by
  intro y_perturbed
  apply Eq.symm
  apply bayesian_encoding_test_leakage_independence split z y y_perturbed m
  intro i hi
  have h_not_test := split.disjoint i hi
  have h_not_j : i ≠ j := by
    intro h_eq
    rw [h_eq] at h_not_test
    exact h_not_test hj
  dsimp [y_perturbed]
  simp [h_not_j]

end Helios

