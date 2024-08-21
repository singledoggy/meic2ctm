import os
import argparse
import datetime

import netCDF4 as nc
import numpy as np
import pandas as pd
import pyproj

from meic2ctm.factor import load_species_map, get_day_factor, get_hour_factor
from meic2ctm.config import config
from meic2ctm.meic import load_meic_dat_by_spec


def main(args):
    # the nc gen main looper
    ts = datetime.datetime.strptime(f'{start} {first_hour}', '%Y-%m-%d %H')
    te = datetime.datetime.strptime(f'{end} 23:59:59', '%Y-%m-%d %H:%M:%S')

    df_spec = load_species_map(config.get('base', 'model'))
    model_specs = df_spec['model_spec'].drop_duplicates().to_list()

    df = pd.read_csv(f"./factor/{config.get('base', 'model')}/species-unit.csv")
    species_unit = dict(zip(df['var'], df['units']))

    # 遍历每一天 一天一个文件
    while ts <= te:
        print(f'calc date: {ts.year}-{ts.month}-{ts.day}')
        oputs = ts

        file = './output/' + ts.strftime('EM_China_d01_%Y%m%d') + ".nc"
        if (os.path.exists(file)):
            os.remove(file)
        ncfile = nc.Dataset(file, 'a', format='NETCDF3_CLASSIC')

        ncfile.createDimension('TSTEP', None)

        # 创建 LAY、ROW、COL 维度
        layers = config.get('projection', 'layers').split(',')
        ncfile.createDimension('LAY', len(layers) - 1)
        ncfile.createDimension('ROW', config.getint('projection', 'ycells'))
        ncfile.createDimension('COL', config.getint('projection', 'xcells'))
        ncfile.createDimension('VAR', len(model_specs))
        ncfile.createDimension('DATE-TIME', 2)

        ncfile.setncattr('FILEDESC', 'Emission aconc generated by meic')
        ncfile.setncattr("GDTYP", "3");
        lambert_params = config.get('projection', 'lambert_params')
        proj = pyproj.Proj(lambert_params)
        # 获取投影参数的具体数值
        P_ALP = proj.srs.split('+lat_1=')[1].split(' ')[0]
        P_BET = proj.srs.split('+lat_2=')[1].split(' ')[0]
        P_GAM = proj.srs.split('+lon_0=')[1].split(' ')[0]
        XCENT = proj.srs.split('+lon_0=')[1].split(' ')[0]
        YCENT = proj.srs.split('+lat_0=')[1].split(' ')[0]

        # 设置 NetCDF 文件的投影属性
        ncfile.setncattr("P_ALP", float(P_ALP))
        ncfile.setncattr("P_BET", float(P_BET))
        ncfile.setncattr("P_GAM", float(P_GAM))
        ncfile.setncattr("XCENT", float(XCENT))
        ncfile.setncattr("YCENT", float(YCENT))

        ncfile.setncattr("XORIG", config.getfloat('projection', 'xorig'));
        ncfile.setncattr("YORIG", config.getfloat('projection', 'yorig'));
        ncfile.setncattr("XCELL", config.getfloat('projection', 'dx'));
        ncfile.setncattr("YCELL", config.getfloat('projection', 'dy'));

        vglvs_array = np.array([float(x.replace('f', '')) for x in config.get('projection', 'layers').split(',')],
                               dtype=np.float32)

        ncfile.setncattr("VGLVLS", vglvs_array);

        formatted_strings = [x.ljust(16) for x in model_specs]
        var_list = ''.join(formatted_strings)
        ncfile.setncattr("VAR-LIST", var_list);
        ncfile.setncattr("FILEDESC", "Emission aconc generated by meic");
        ncfile.setncattr("HISTORY", "");
        ncfile.setncattr("FTYPE", int(1));
        ncfile.setncattr("TSTEP", int(10000));
        ncfile.setncattr("NTHIK", int(1));
        ncfile.setncattr("VGTYP", int(7));
        ncfile.setncattr("VGTOP", int(10000));
        ncfile.setncattr("GDTYP", int(-9999));
        ncfile.setncattr("GDNAM", "MEIC2");
        ncfile.setncattr("UPNAM", "MEIC2");

        ncfile.setncattr("EXEC_ID", "__EP_CMAQ__");

        ncfile.setncattr("CDATE", int(datetime.datetime.now().strftime('%Y%j')));
        ncfile.setncattr("CTIME", 0);
        ncfile.setncattr("WDATE", int(datetime.datetime.now().strftime('%Y%j')));
        ncfile.setncattr("WTIME", 0);
        ncfile.setncattr("SDATE", int(ts.strftime('%Y%j')));
        ncfile.setncattr("STIME", int(first_hour * 10000));

        ncfile.setncattr("NCOLS", config.getint('projection', 'xcells'));
        ncfile.setncattr("NROWS", config.getint('projection', 'ycells'));
        ncfile.setncattr("NLAYS", len(layers) - 1);

        var = ncfile.createVariable('TFLAG', 'i', ('TSTEP', 'VAR', 'DATE-TIME'))
        var.setncattr('units', '<YYYYDDD,HHMMSS>')
        var.setncattr('long_name', 'TFLAG'.ljust(16))
        var.setncattr('var_desc', "Timestep-valid flags: (1) YYYYDDD or (2) HHMMSS".ljust(80))

        # 创建新的变量，并指定维度
        for spec in model_specs:
            var = ncfile.createVariable(spec, 'f4', ('TSTEP', 'LAY', 'ROW', 'COL'))
            var.setncattr('units', species_unit[spec].ljust(16))
            var.setncattr('long_name', spec.ljust(16))
            var.setncattr('var_desc', ("Model species " + spec).ljust(80))

        model_specs = df_spec['model_spec'].drop_duplicates().to_list()

        ncfile.setncattr("NVARS", len(model_specs));

        for hour in range(0, one_file_hours):
            # 当有跨月的计算需求的时候重新计算meic数据
            if hour > 0:
                oputs = ts + datetime.timedelta(hours=hour)
            print('Processing hour {}'.format(oputs.hour))

            yyyyDDD = oputs.year * 1000 + oputs.timetuple().tm_yday
            HH0000 = oputs.hour * 10000
            tflag = [yyyyDDD, HH0000]

            spec_index = 0

            for spec in model_specs:
                hour_result = None

                meic_month_data = load_meic_dat_by_spec(oputs.year, oputs.month, spec)
                for sector in meic_month_data:
                    day_factor = get_day_factor(oputs.year, oputs.month, oputs.day, sector)
                    hour_factor = get_hour_factor(oputs.hour, sector)
                    if hour_result is None:
                        hour_result = meic_month_data[sector] * (day_factor * hour_factor)
                    else:
                        hour_result += meic_month_data[sector] * (day_factor * hour_factor)

                var = ncfile.variables['TFLAG']
                var[hour, spec_index, :] = tflag
                spec_index += 1

                var = ncfile.variables[spec]
                var[hour, :, :, :] = hour_result

        ncfile.close()

        ts += datetime.timedelta(days=1)


# if __name__ == '__main__':

parser = argparse.ArgumentParser(description='split the nc to model ready nc.')
parser.add_argument('-s', '--start', help='change the start datetime', type=str, default=None)
parser.add_argument('-e', '--end', help='charnge the end datetime', type=str, default=None)

try:
    args = parser.parse_args()
except argparse.ArgumentError:
    print('Catching an argument Error!')

# cli 指定参数优先
one_file_hours = config.getint('time', 'one_file_hours')
first_hour = config.getint('time', 'first_hour')
start = args.start if args.start else config.get('time', 'start_date')
end = args.end if args.end else config.get('time', 'end_date')
main(args)
