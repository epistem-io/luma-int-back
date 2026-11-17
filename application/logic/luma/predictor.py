from application import db

from application.utils.common import AppMessageException
from application.utils.common import ErrorCodeEnum

TERRAIN_PREDICTORS = ["ELEVATION", "SLOPE", "ASPECT"]
SPECTRAL_PREDICTORS = [
    "NDVI", "EVI", "SAVI", "MSAVI", "OSAVI", "ARVI", "GBNDVI", "GNDVI",   # Vegetasi
    "MNDWI", "NDMI", "AWEInsh",                                            # Air & Kelembaban
    "NDBI", "DBSI", "MBI",                                                 # Tanah dan Lahan Terbangun
]
CONFLICTING_PREDICTORS = [("EVI", "SAVI")]

def set_predictor_config(known_session, luma, predictors):
    for p in predictors:
        if not isinstance(p, str):
            raise AppMessageException('invalid input: predictor, format: list of strings', error=ErrorCodeEnum.ERR_VALIDATION)
        if p not in TERRAIN_PREDICTORS and p not in SPECTRAL_PREDICTORS:
            raise AppMessageException('invalid input: predictor, format: list of valid predictor names', error=ErrorCodeEnum.ERR_VALIDATION)
    for a, b in CONFLICTING_PREDICTORS:
        if a in predictors and b in predictors:
            raise AppMessageException('invalid input: predictor, {} and {} cannot be selected together'.format(a, b), error=ErrorCodeEnum.ERR_VALIDATION)

    spectral_indices = [p for p in predictors if p in SPECTRAL_PREDICTORS]
    predictor_config = {
        "individual_predictors": {
            "elevation": "ELEVATION" in predictors,
            "slope": "SLOPE" in predictors,
            "aspect": "ASPECT" in predictors,
            "spectral_indices": spectral_indices
        },
        "terrain": any(p in TERRAIN_PREDICTORS for p in predictors),
        "spectral_indices": spectral_indices,
        "index_coefficients": {}
    }

    luma.use_predictor = predictor_config.get('terrain') or len(spectral_indices) > 0
    luma.predictor_config = predictor_config

    db.session.add(luma)
    db.session.commit()