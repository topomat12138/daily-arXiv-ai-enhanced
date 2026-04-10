from pydantic import BaseModel, Field, field_validator
import re

class Structure(BaseModel):
    tldr: str = Field(description="a concise summary of the paper")
    method: str = Field(description="the main method or approach used in the paper")
    tags: str = Field(
    description=(
        "comma-separated keywords describing the topics most relevant to the paper, "
        "especially among:\n"
        "quantum_geometry,\n"
        "topology,\n"
        "altermagnetic,\n"
        "superconducting_impurity,\n"
        "vortex,\n"
        "pi_junction,\n"
        "machine_learning,\n"
        "quantum_computing,\n"
        "quantum_devices"
                )
    )
