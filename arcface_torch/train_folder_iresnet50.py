import os
import math
import torch
import torch.nn as nn
import torch.nn.functional as F

from tqdm import tqdm
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, transforms

from backbones import get_model
from configs.casia_iresnet50_finetune import config


class ArcFaceHead(nn.Module):
    def __init__(self, embedding_size, num_classes, s=64.0, m=0.5):
        super().__init__()

        self.s = s
        self.m = m

        self.weight = nn.Parameter(
            torch.FloatTensor(num_classes, embedding_size)
        )
        nn.init.xavier_uniform_(self.weight)

        self.cos_m = math.cos(m)
        self.sin_m = math.sin(m)
        self.th = math.cos(math.pi - m)
        self.mm = math.sin(math.pi - m) * m

    def forward(self, embeddings, labels):
        cosine = F.linear(
            F.normalize(embeddings),
            F.normalize(self.weight)
        )

        sine = torch.sqrt(torch.clamp(1.0 - cosine ** 2, min=1e-7))
        phi = cosine * self.cos_m - sine * self.sin_m

        phi = torch.where(
            cosine > self.th,
            phi,
            cosine - self.mm
        )

        one_hot = torch.zeros_like(cosine)
        one_hot.scatter_(1, labels.view(-1, 1), 1.0)

        logits = one_hot * phi + (1.0 - one_hot) * cosine
        logits *= self.s

        return logits


def load_pretrained_backbone(backbone, path):
    print("Loading pretrained backbone:", path)

    state_dict = torch.load(path, map_location="cpu")

    if isinstance(state_dict, dict):
        if "state_dict_backbone" in state_dict:
            state_dict = state_dict["state_dict_backbone"]
        elif "backbone" in state_dict:
            state_dict = state_dict["backbone"]
        elif "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]

    clean_state_dict = {}

    for k, v in state_dict.items():
        if k.startswith("module."):
            k = k[7:]
        clean_state_dict[k] = v

    missing, unexpected = backbone.load_state_dict(
        clean_state_dict,
        strict=False
    )

    print("Missing keys:", missing)
    print("Unexpected keys:", unexpected)


def load_resume_checkpoint(backbone, head, checkpoint_path):
    print("Resume checkpoint:", checkpoint_path)

    checkpoint = torch.load(checkpoint_path, map_location="cpu")

    if "backbone" not in checkpoint:
        raise KeyError("Checkpoint không có key 'backbone'.")

    if "arcface_head" not in checkpoint:
        raise KeyError("Checkpoint không có key 'arcface_head'.")

    backbone.load_state_dict(
        checkpoint["backbone"],
        strict=True
    )

    head.load_state_dict(
        checkpoint["arcface_head"],
        strict=True
    )

    print("Loaded backbone + ArcFace head from checkpoint.")


def set_train_mode(backbone, mode):
    if mode == "head_only":
        for p in backbone.parameters():
            p.requires_grad = False

        print("Mode: head_only")
        print("Trainable: ArcFace head only")

    elif mode == "layer4":
        for p in backbone.parameters():
            p.requires_grad = False

        for name, p in backbone.named_parameters():
            if (
                "layer4" in name
                or "features" in name
                or "fc" in name
                or "bn2" in name
            ):
                p.requires_grad = True

        print("Mode: layer4")
        print("Trainable: last layers + ArcFace head")

    elif mode == "full":
        for p in backbone.parameters():
            p.requires_grad = True

        print("Mode: full")
        print("Trainable: full backbone + ArcFace head")

    else:
        raise ValueError("mode must be: head_only, layer4, full")

    trainable = sum(p.numel() for p in backbone.parameters() if p.requires_grad)
    total = sum(p.numel() for p in backbone.parameters())

    print(f"Backbone trainable params: {trainable:,} / {total:,}")


@torch.no_grad()
def evaluate(backbone, head, loader, criterion, device, fp16):
    backbone.eval()
    head.eval()

    total_loss = 0.0
    correct = 0
    total = 0

    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        with torch.cuda.amp.autocast(enabled=fp16):
            embeddings = backbone(images)
            logits = head(embeddings, labels)
            loss = criterion(logits, labels)

        total_loss += loss.item()

        preds = torch.argmax(logits, dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return total_loss / len(loader), correct / total


def train():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("Device:", device)

    torch.backends.cudnn.benchmark = True

    transform = transforms.Compose([
        transforms.Resize((112, 112)),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.ColorJitter(
            brightness=0.2,
            contrast=0.2,
            saturation=0.2
        ),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.5, 0.5, 0.5],
            std=[0.5, 0.5, 0.5]
        )
    ])

    dataset = datasets.ImageFolder(
        root=config.data,
        transform=transform
    )

    num_classes = len(dataset.classes)

    print("Dataset:", config.data)
    print("Number of identities:", num_classes)
    print("Number of images:", len(dataset))
    print("First classes:", dataset.classes[:5])

    val_size = max(1, int(len(dataset) * config.val_ratio))
    train_size = len(dataset) - val_size

    train_set, val_set = random_split(
        dataset,
        [train_size, val_size],
        generator=torch.Generator().manual_seed(42)
    )

    train_loader = DataLoader(
        train_set,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        pin_memory=True,
        persistent_workers=True if config.num_workers > 0 else False
    )

    val_loader = DataLoader(
        val_set,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
        pin_memory=True,
        persistent_workers=True if config.num_workers > 0 else False
    )

    backbone = get_model(
        config.network,
        dropout=0.0,
        fp16=config.fp16,
        num_features=config.embedding_size
    ).to(device)

    load_pretrained_backbone(
        backbone,
        config.pretrained
    )

    head = ArcFaceHead(
        embedding_size=config.embedding_size,
        num_classes=num_classes,
        s=config.scale,
        m=config.margin
    ).to(device)

    if hasattr(config, "resume_checkpoint") and config.resume_checkpoint != "":
        load_resume_checkpoint(
            backbone,
            head,
            config.resume_checkpoint
        )

    elif hasattr(config, "resume_backbone") and config.resume_backbone != "":
        print("Resume backbone:", config.resume_backbone)

        resume_state = torch.load(
            config.resume_backbone,
            map_location="cpu"
        )

        backbone.load_state_dict(
            resume_state,
            strict=True
        )

    set_train_mode(
        backbone,
        config.mode
    )

    criterion = nn.CrossEntropyLoss()

    params = list(
        filter(lambda p: p.requires_grad, backbone.parameters())
    )
    params += list(head.parameters())

    optimizer = torch.optim.SGD(
        params,
        lr=config.lr,
        momentum=0.9,
        weight_decay=config.weight_decay
    )

    scheduler = torch.optim.lr_scheduler.StepLR(
        optimizer,
        step_size=config.step_size,
        gamma=config.gamma
    )

    scaler = torch.cuda.amp.GradScaler(enabled=config.fp16)

    os.makedirs(config.output, exist_ok=True)

    best_val_loss = float("inf")

    for epoch in range(config.epochs):
        backbone.train()
        head.train()

        total_loss = 0.0
        correct = 0
        total = 0

        pbar = tqdm(
            train_loader,
            desc=f"Epoch {epoch + 1}/{config.epochs}"
        )

        for images, labels in pbar:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)

            optimizer.zero_grad()

            with torch.cuda.amp.autocast(enabled=config.fp16):
                embeddings = backbone(images)
                logits = head(embeddings, labels)
                loss = criterion(logits, labels)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            total_loss += loss.item()

            preds = torch.argmax(logits, dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            pbar.set_postfix({
                "loss": f"{loss.item():.4f}",
                "acc": f"{correct / total:.4f}"
            })

        scheduler.step()

        train_loss = total_loss / len(train_loader)
        train_acc = correct / total

        val_loss, val_acc = evaluate(
            backbone,
            head,
            val_loader,
            criterion,
            device,
            config.fp16
        )

        current_lr = optimizer.param_groups[0]["lr"]

        print(
            f"\nEpoch {epoch + 1}/{config.epochs}\n"
            f"Train Loss : {train_loss:.4f}\n"
            f"Train Acc  : {train_acc:.4f}\n"
            f"Val Loss   : {val_loss:.4f}\n"
            f"Val Acc    : {val_acc:.4f}\n"
            f"Best Val   : {best_val_loss:.4f}\n"
            f"LR         : {current_lr:.7f}\n"
        )

        checkpoint = {
            "epoch": epoch + 1,
            "backbone": backbone.state_dict(),
            "arcface_head": head.state_dict(),
            "num_classes": num_classes,
            "classes": dataset.classes,
            "embedding_size": config.embedding_size
        }

        torch.save(
            checkpoint,
            os.path.join(config.output, "last_checkpoint.pth")
        )

        torch.save(
            backbone.state_dict(),
            os.path.join(config.output, "last_backbone.pth")
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss

            torch.save(
                checkpoint,
                os.path.join(config.output, "best_checkpoint.pth")
            )

            torch.save(
                backbone.state_dict(),
                os.path.join(config.output, "best_backbone.pth")
            )

            print("Saved best model.")

    print("Training done.")
    print("Best backbone:", os.path.join(config.output, "best_backbone.pth"))


if __name__ == "__main__":
    train()