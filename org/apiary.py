from typing import Dict


def get_teams() -> Dict[int, str]:
    """
    Retrieve map of team choices from Apiary.
    TODO make this an API call
    """
    return {
        1: "RoboNav",
        2: "BattleBots",
        3: "Outreach",
        4: "RoboCup",
        5: "RoboRacing",
        6: "Core",
        7: "Mechanical Training",
        8: "Software Training",
        9: "Electrical Training",
        11: "Corporate",
        12: "Spring Training",
        13: "RoboWrestling",
        14: "Firmware Training",
        15: "Electrical Core",
        16: "Software Core",
        17: "Mechanical Core",
        18: "People Counter Import",
        19: "Finance",
    }
