import os

# from loguru import logger


class EPlusOutputFormatter:
    ignored = [
        # These are the messages counted as Severe, but actually ok (desired)
        "   ** Severe  ** ExternalInterface: Received end of simulation flag"
    ]

    @classmethod
    def group_into_csv(cls, episode_dir: str) -> None:
        file_csv = episode_dir + "/eplusout.csv"
        # file_err = episode_dir + '/eplusout.err'
        # files_to_preserve ['eplusout.csv', 'eplusout.err', 'eplustbl.htm']
        files_to_clean = [
            "eplusmtr.csv",
            "eplusout.audit",
            "eplusout.bnd",
            "eplusout.dxf",
            "eplusout.eio",  # 'eplusout.edd',
            "eplusout.end",
            "eplusout.eso",
            "eplusout.mdd",
            "eplusout.mtd",
            "eplusout.mtr",  # 'eplusout.rdd',
            "eplusout.rvaudit",
            "eplusout.shd",
            "eplusssz.csv",
            "epluszsz.csv",
            "sqlite.err",
            "eplusout.dbg",
            "eplustbl.htm",
        ]

        # Check for any severe error
        # num_errors = cls._count_severe_errors(file_err)
        # if num_errors != 0:
        #     logger.warning('EnergyPlusEnv: Severe error(s) occurred. Error count: {}'.format(num_errors))
        #     logger.warning('EnergyPlusEnv: Check contents of {}'.format(file_err))
        # sys.exit(1)

        # Remove unnecessary files
        # If csv file is not present in some reason, preserve all other files for inspection
        for file in files_to_clean:
            file_path = episode_dir + "/" + file
            if os.path.isfile(file_path):
                os.remove(file_path)

        assert os.path.isfile(file_csv), "eplusout.csv not found!"

    @classmethod
    def _count_severe_errors(cls, file: str) -> int:

        if not os.path.isfile(file):
            return -1  # Error count is unknown
        fd = open(file)
        lines = fd.readlines()
        fd.close()
        num_ignored = 0
        for line in lines:
            if line.find("************* EnergyPlus Completed Successfully") >= 0:
                tokens = line.split()
                return int(tokens[6]) - num_ignored
            for pattern in cls.ignored:
                if pattern in line:
                    num_ignored += 1
                    break
        return -1
