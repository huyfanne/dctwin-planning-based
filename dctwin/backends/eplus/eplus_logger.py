import gzip
import os
import shutil
# from loguru import logger


class EPlusOutputFormatter:
    ignored = [
        # These are the messages counted as Severe, but actually ok (desired)
        '   ** Severe  ** ExternalInterface: Received end of simulation flag'
    ]

    @classmethod
    def group_into_csv(cls, episode_dir: str) -> None:
        file_csv = episode_dir + '/eplusout.csv'
        file_csv_gz = episode_dir + '/eplusout.csv.gz'
        # file_err = episode_dir + '/eplusout.err'
        # files_to_preserve ['eplusout.csv', 'eplusout.err', 'eplustbl.htm']
        files_to_clean = ['eplusmtr.csv', 'eplusout.audit', 'eplusout.bnd',
                          'eplusout.dxf', 'eplusout.eio', 'eplusout.edd',
                          'eplusout.end', 'eplusout.eso', 'eplusout.mdd',
                          'eplusout.mtd', 'eplusout.mtr', 'eplusout.rdd',
                          'eplusout.rvaudit', 'eplusout.shd', 'eplusssz.csv',
                          'epluszsz.csv', 'sqlite.err']

        # Check for any severe error
        # num_errors = cls._count_severe_errors(file_err)
        # if num_errors != 0:
        #     logger.warning('EnergyPlusEnv: Severe error(s) occurred. Error count: {}'.format(num_errors))
        #     logger.warning('EnergyPlusEnv: Check contents of {}'.format(file_err))
            # sys.exit(1)

        # Compress csv file and remove unnecessary files
        # If csv file is not present in some reason, preserve all other files for inspection
        if os.path.isfile(file_csv):
            with open(file_csv, 'rb') as f_in:
                with gzip.open(file_csv_gz, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(file_csv)

            for file in files_to_clean:
                file_path = episode_dir + '/' + file
                if os.path.isfile(file_path):
                    os.remove(file_path)

    @classmethod
    def _count_severe_errors(cls, file : str) -> int:

        if not os.path.isfile(file):
            return -1  # Error count is unknown
        fd = open(file)
        lines = fd.readlines()
        fd.close()
        num_ignored = 0
        for line in lines:
            if line.find('************* EnergyPlus Completed Successfully') >= 0:
                tokens = line.split()
                return int(tokens[6]) - num_ignored
            for pattern in cls.ignored:
                if pattern in line:
                    num_ignored += 1
                    break
        return -1
