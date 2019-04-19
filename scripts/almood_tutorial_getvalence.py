#! /usr/bin/env python
# -*- encoding: UTF-8 -*-

"""Example: Use currentPersonState Method"""

import qi
import argparse
import sys
import time


def main(in_session):
    """
    This example uses the currentPersonState method.
    """
    # Get the service ALMood.

    mood_service = in_session.service("ALMood")
    mood_service.subscribe("Tutorial_GetValence", "Active")
    # The pre-loading of all ALMood extractors may take up to 3 seconds:
    time.sleep(3)
    print mood_service.currentPersonState()["valence"]["value"]

    mood_service.unsubscribe("Tutorial_GetValence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, default="127.0.0.1",
                        help="Robot IP address. On robot or Local Naoqi: use '127.0.0.1'.")
    parser.add_argument("--port", type=int, default=9559,
                        help="Naoqi port number")

    args = parser.parse_args()
    session = qi.Session()
    try:
        session.connect("tcp://" + args.ip + ":" + str(args.port))
    except RuntimeError:
        print ("Can't connect to Naoqi at ip \"" + args.ip + "\" on port " + str(args.port) + ".\n"
               "Please check your script arguments. Run with -h option for help.")
        sys.exit(1)
    main(session)
