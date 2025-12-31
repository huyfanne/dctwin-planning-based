import pandas as pd
import warnings

# Suppress the numpy.find_common_type deprecation warning from pandas
warnings.filterwarnings('ignore', message='.*np.find_common_type.*', category=DeprecationWarning)

# Simple approach: read and pivot
file_path = '/Users/rda001/Documents/dctwin/test/log/ba1604-dh2/base/postProcessing/yPlusWallFunction/0/yPlus.dat'

# Read file, skipping comment lines, using whitespace separator
df = pd.read_csv(file_path, sep=r'\s+', comment='#', 
                 names=['Time', 'patch', 'min', 'max', 'average'])

# Pivot: patches as rows, times as columns (using average column)
df_pivot = df.pivot(index='patch', columns='Time', values='average').reset_index()

# Rename time columns to 'time=1', 'time=2', etc.
df_pivot.columns = ['patch'] + [f'time={int(col)}' for col in df_pivot.columns[1:]]


print(df_pivot.iloc[:, -1].mean())

