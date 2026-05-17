from application import db

from application.utils.common import AppMessageException
from application.utils.common import ErrorCodeEnum

def set_predictor_config(known_session, luma, predictors):
    for p in predictors:
        if not isinstance(p, str):
            raise AppMessageException('invalid input: predictor, format: list of strings', error=ErrorCodeEnum.ERR_VALIDATION)
        if p not in {
            "ELEVATION": "Terrain: Elevation",
            "SLOPE"    : "Terrain: Slope",
            "ASPECT"   : "Terrain: Aspect",
            "NDVI"     : "Vegetasi", 
            "EVI"      : "Vegetasi", 
            "SAVI"     : "Vegetasi",
            "MSAVI"    : "Vegetasi",
            "OSAVI"    : "Vegetasi",
            "ARVI"     : "Vegetasi",
            "GBNDVI"   : "Vegetasi",
            "GNDVI"    : "Vegetasi",
            "MNDWI"    : "Air & Kelembaban",
            "NDMI"     : "Air & Kelembaban",
            "AWEInsh"  : "Air & Kelembaban",
            "NDBI"     : "Tanah dan Lahan Terbangun",
            "DBSI"     : "Tanah dan Lahan Terbangun",
            "MBI"      : "Tanah dan Lahan Terbangun"
        }.keys():
            raise AppMessageException('invalid input: predictor, format: list of valid predictor names', error=ErrorCodeEnum.ERR_VALIDATION)
    
    spectral_indices = [p for p in predictors if p not in ["ELEVATION", "SLOPE", "ASPECT"]]
    predictor_config = {
        "individual_predictors": {
            "elevation": "ELEVATION" in predictors,
            "slope": "SLOPE" in predictors,
            "aspect": "ASPECT" in predictors,
            "spectral_indices": spectral_indices
        },
        "terrain": "ELEVATION" in predictors or "SLOPE" in predictors or "ASPECT" in predictors,
        "spectral_indices": spectral_indices,
        # Add coefficient support
        "index_coefficients": {}
    }
    
    luma.use_predictor = predictor_config.get('terrain') or len(spectral_indices) > 0
    luma.predictor_config = predictor_config
    
    db.session.add(luma)
    db.session.commit()