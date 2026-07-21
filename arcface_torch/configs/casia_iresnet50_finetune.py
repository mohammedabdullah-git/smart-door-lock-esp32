from easydict import EasyDict as edict

config = edict()

config.data = "dataset_images_1000"

# Fallback, thực tế sẽ resume từ checkpoint phase 3
config.pretrained = "work_dirs/1000_phase3_full/last_backbone.pth"

config.output = "work_dirs/1000_phase3_full_continue"

config.network = "r50"
config.embedding_size = 512

config.mode = "full"

# Train tiếp rất nhẹ
config.epochs = 3
config.batch_size = 16
config.num_workers = 4

# LR nhỏ hơn để tránh overfit/phá embedding
config.lr = 0.000001
config.weight_decay = 5e-4

config.scale = 64.0
config.margin = 0.5

config.val_ratio = 0.02

# Không giảm LR thêm quá sớm
config.step_size = 3
config.gamma = 0.1

config.fp16 = True

config.resume_backbone = ""
config.resume_checkpoint = "work_dirs/1000_phase3_full/last_checkpoint.pth"