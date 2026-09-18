# Citation to Artifact

## Artifact identity

| Field | Value |
|---|---|
| Artifact | Helios LST reproducibility artifact |
| Version | 1.0.0 |
| Date | 2026-09-18 |
| Corresponds to | Manuscript v12, *"Measurement and Prediction of Land Surface Temperature in Chennai and Bangalore, India, Using a Polyglot Machine Learning Pipeline and Landsat 8/9 Imagery"* (Urban Climate submission) |
| License | MIT (code, models, figures) · CC-BY-4.0 (data deposits) — see `LICENSE` |

## Versioning scheme

`MAJOR.MINOR.PATCH` where MAJOR tracks the manuscript version set it
supports (1.x ↔ v12 and its minor revisions). Result-file changes within a
manuscript revision bump PATCH; any change to shipped checkpoints bumps
MINOR and regenerates `manifest/checkpoint_sha256.txt`.

## How to cite

**Software / artifact:**

> Desai, P., & Mandal, H. N. (2026). *Helios: reproducibility artifact for
> "Measurement and Prediction of Land Surface Temperature in Chennai and
> Bangalore, India"* (v1.0.0). Zenodo. DOI pending deposit.

**Paper:**

> Desai, P., & Mandal, H. N. Measurement and Prediction of Land Surface
> Temperature in Chennai and Bangalore, India, Using a Polyglot Machine
> Learning Pipeline and Landsat 8/9 Imagery. *Urban Climate* (under review).

## Deposit checklist (before submission)

- [ ] Zip the repository at the tagged commit (excluding `.git`, `staging/`,
      `.venv/`, `target/`)
- [ ] Deposit the zip on Zenodo; record the DOI above
- [ ] Deposit regenerated data products (scene inventory CSV, dense-matrix
      schemas) as a separate CC-BY-4.0 Zenodo record
- [ ] Update the Data availability statement in `main.tex` with the DOI

## Related identifiers

- Planetary Computer STAC API: `https://planetarycomputer.microsoft.com/api/stac/v1`
- USGS LandsatLook STAC: `https://landsatlook.usgs.gov/stac-server`
- OpenStreetMap: © OpenStreetMap contributors (ODbL)
