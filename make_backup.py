from datetime import datetime
from shutil import copyfile
import os

src_dir = '/home/ajcav2/mechwatchbot/mechwatchbot/'
dst_dir = '/home/ajcav2/mechwatchbot/mechwatchbot/userlist_backup/'
default_filename = 'userlist'
default_ext = '.pickle'
max_num_files = 35

list_of_files = os.listdir(dst_dir)
full_path = [os.path.join(dst_dir, x) for x in list_of_files]
if len(list_of_files) == max_num_files:
    oldest_file = min(full_path, key=os.path.getctime)
    os.remove(oldest_file)

now = str(datetime.now())
print(f"Making copy at: {now}.")

src_file = os.path.join(src_dir, default_filename+default_ext)
dst_file = os.path.join(dst_dir, default_filename+'_'+now+default_ext)
copyfile(src_file, dst_file)

print("Copy complete.")
