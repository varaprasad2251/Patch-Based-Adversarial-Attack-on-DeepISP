# CIS_Project

<!-- Command to generate raw images with patch from raw images
```bash
python3 patch_gen.py --input_dir input_raw_images --output_dir raw_images_patch --start_pos 50 50 --patch_area 0.1
```


Command to generate ssim score between final images and final images with patch
```bash
python3 ssim_score_gen.py output_images output_images_patch
```

Go into project folder and then run 

```bash
./automation.sh
``` -->

Command to run patch optimization code from the project root directory.
```bash
python3 DeepISP/patch_optimization.py -in 1115
```

**in** is the input file number from DeepISP/input_raw_images folder. eg: 1115



Command to run object Detection code from the project root directory.
```bash
python3 YOLO/YOLOv8.py -in 1115
```

**in** is the input file number from DeepISP/patch_results folder. eg: 1115





