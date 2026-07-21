from .iresnet import iresnet18
from .iresnet import iresnet34
from .iresnet import iresnet50
from .iresnet import iresnet100
from .iresnet import iresnet200


def get_model(name, **kwargs):

    if name == "r18":
        return iresnet18(False, **kwargs)

    elif name == "r34":
        return iresnet34(False, **kwargs)

    elif name == "r50":
        return iresnet50(False, **kwargs)

    elif name == "r100":
        return iresnet100(False, **kwargs)

    elif name == "r200":
        return iresnet200(False, **kwargs)

    else:
        raise ValueError(f"Unknown backbone: {name}")