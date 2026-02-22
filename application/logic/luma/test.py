from luma_ge.sample_data import SyncTrainData

def test_load_training_data(aoi):
    TrainEePath = 'projects/ee-rg2icraf/assets/Indonesia_lulc_Sample'
    TrainField = 'kelas'

    try:
        TrainDataDict = SyncTrainData.LoadTrainData(
            landcover_df={},
            aoi_geometry=aoi,
            training_shp_path=None,
            training_ee_path=TrainEePath
        )
        print(TrainDataDict)
    except Exception as e:
        print('error test_load_training_data: {}'.format(e))
        print('error test_load_training_data: {}'.format(e))
        print('error test_load_training_data: {}'.format(e))
        print('error test_load_training_data: {}'.format(e))
        print('error test_load_training_data: {}'.format(e))