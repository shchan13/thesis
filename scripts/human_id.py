#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This is for human identification
"""
import rospy
import rosgraph
import rospkg

from jsk_gui_msgs.msg import VoiceMessage
from tfpose_ros.msg import Persons
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from thesis.msg import Human
from rospy_message_converter import message_converter

import sys
import os
import qi

import cv2
import numpy as np
import pandas as pd
from numpy.linalg import norm
import yaml


def get_ip(data):
    callerid = data._connection_header['callerid']  # type: 'str'
    master = rosgraph.Master('listener')
    ip = master.lookupNode(callerid)
    ip_num = ip.split(':')[1][2:]  # type: 'str'

    print 'ip_num = ', ip_num
    print 'data = ', data

    return ip_num


def get_joint_color(img, joints, j_features):
    """
    get the color of pixel where the joints are
    :param img: BGR input image for openpose, np.array(height, width, 3)
    :param joints: the joints from OpenPose in pixel unit
    :param j_features: lists of numbers of joints, [1, 2, 5]
    :return: 2D array of RGB colors, np.array([[b1, g1, r1], [b2, g2, r2], [b3, g3, r3]]), shape=(-1, 3)
    """
    if j_features is None:
        j_features = [1, 2, 5]

    colors = np.array([]).astype(np.int8)

    for j in j_features:
        if np.all(joints[j] > 0):
            colors = np.append(colors, img[joints[j, 1], joints[j, 0], :])

        else:
            colors = np.append(colors, np.array([-1, -1, -1]))

    colors = colors.reshape(-1, 3)

    return colors


def get_people_joints(human_pose):
    person_list = []  # a list of 2D array
    head_chest_range = 20  # distance threshold btw joint[0] and joint[1]
    part_number = 18

    for idx, person in enumerate(human_pose.persons):
        joints = np.ones((part_number, 2), dtype=np.int) * -1
        for i in range(len(human_pose.persons[idx].body_part)):
            part = human_pose.persons[idx].body_part[i]
            # Transform the joint points back to the position on the image
            joints[part.part_id, 0] = part.x * human_pose.image_w
            joints[part.part_id, 1] = part.y * human_pose.image_h

        # filtering person who is too far or no head
        if np.all(joints[0] > 0) and (np.all(joints[16] > 0) or np.all(joints[17] > 0)):  # person has nose and one ear
            if np.all(joints[1] > 0):  # person has chest
                if norm(joints[0] - joints[1]) > head_chest_range:  # filtering person who is too far
                    person_list.append(joints)

            elif np.all(joints[2] > 0):
                if norm(joints[0] - joints[2]) > head_chest_range:  # filtering person who is too far
                    person_list.append(joints)

            elif np.all(joints[5] > 0):
                if norm(joints[0] - joints[5]) > head_chest_range:  # filtering person who is too far
                    person_list.append(joints)

    return person_list


def color_dist(c1, c2):
    """
    Check the shirt color similarity based on cosine similarity.
    :param c1: int np.array with shape=(features, 3) in BGR order
    :param c2: int np.array with shape=(features, 3) in BGR order
    :return: a scalar of average color distance, ignoring the negative values
    """

    c_dis = np.zeros(c1.shape[0])  # color distance
    for i in range(len(c_dis)):
        if np.all(c1[i]) >= 0 and np.all(c2[i]) >= 0:
            r_mean = (c1[i][2] + c2[i][2]) / 2.
            d_r = c1[i][2] - c2[i][2]
            d_g = c1[i][1] - c2[i][1]
            d_b = c1[i][0] - c2[i][0]
            c_dis[i] = np.sqrt((512.+r_mean)*d_r*d_r/256. + 4.*d_g*d_g + (767.-r_mean)*d_b*d_b/256.)

    # if __debug__:
    #     print 'color distance = ', c_dis

    return np.mean(c_dis)


def identify_human(h_info, j_features, person_list):
    if h_info is None:
        h_info = load_human_info(rospkg.RosPack().get_path('thesis') + '/human_info/')

    if j_features is None:
        j_features = [1, 2, 5]

    if person_list is None:
        try:
            human_pose = rospy.wait_for_message('/thesis/human_pose', Persons, timeout=10)
        except rospy.exceptions.ROSException:
            rospy.logerr("Error when fetching human_pose.")
            return

        person_list = get_people_joints(human_pose)

    try:
        img_stitch = cv_bridge.imgmsg_to_cv2(rospy.wait_for_message('/thesis/img_stitching', Image, timeout=10), "bgr8")

    except rospy.exceptions.ROSException:
        rospy.logerr("Error when fetching img_stitching.")
        return

    for joints in person_list:
        identify_single_human(img_stitch, joints, h_info, j_features)

    return


def identify_single_human(img, joints, h_info, j_features):
    if h_info is None:
        h_info = load_human_info(rospkg.RosPack().get_path('thesis') + '/human_info/')

    if j_features is None:
        j_features = [1, 2, 5]

    colors = get_joint_color(img, joints, j_features)
    temp_sim = np.zeros(len(h_info))

    for i, human in enumerate(h_info):
        temp_sim[i] = color_dist(colors, human.shirt_color)

    human_result = h_info[np.argmin(temp_sim)] if np.min(temp_sim) < 150. else None

    if human_result is None:
        print "New to this person."

    else:
        print 'similar to ', human_result.name

    return human_result


def show_color(colors):
    """
    Show the cloth color
    :param colors: list of np.array([b, g, r])
    :return: showing a 50x50 image per color for t seconds
    """
    w = 50
    s = 5
    t = 1
    vis_color = np.ones((w, w*len(colors) + s * (len(colors)-1), 3)).astype(np.uint8) * 255

    for i, c in enumerate(colors):
        if np.any(c) == -1:  # invalid color
            i -= 1
            continue

        vis_color[:, i*(w+s):i*(w+s)+w, :] = np.tile(c, (w, w, 1))

    cv2.imshow('vis_color', vis_color)
    cv2.waitKey(1000*t)

    return


def greeting_cb():
    tts_service.say('Hi, I am Pepper. Nice to meet you. What is your name?')
    print 'What is your name?'
    voice_msg = rospy.wait_for_message('/Tablet/voice', VoiceMessage)  # type: VoiceMessage
    print voice_msg

    ip_num = get_ip(voice_msg)
    name = voice_msg.texts[0].split(' ')[0]

    print 'ip = ', ip_num
    print 'name = ', name

    try:
        img_stitch = cv_bridge.imgmsg_to_cv2(rospy.wait_for_message('/thesis/img_stitching', Image, timeout=10), "bgr8")
        human_pose = rospy.wait_for_message('/thesis/human_pose', Persons, timeout=10)

    except rospy.exceptions.ROSException:
        return

    max_dis = 0
    max_joints = np.ones((part_num, 2), dtype=np.int) * -1
    for idx, person in enumerate(human_pose.persons):
        joints = np.ones((part_num, 2), dtype=np.int) * -1
        for i in range(len(human_pose.persons[idx].body_part)):
            part = human_pose.persons[idx].body_part[i]
            # Transform the joint points back to the position on the image
            joints[part.part_id, 0] = part.x * human_pose.image_w
            joints[part.part_id, 1] = part.y * human_pose.image_h

        # Pick person with longest distance of joint0 and joint1
        if np.all(joints[2] > 0) and np.all(joints[5] > 0):  # person has nose and one ear
            if norm(joints[2] - joints[5]) > max_dis:
                max_dis = norm(joints[2] - joints[5])
                max_joints = joints

    if np.all(max_joints == -1):
        print 'no human in the front.'

    else:
        # Show picked joint
        colors = get_joint_color(img_stitch, max_joints, joints_features)
        show_color(colors)

        # Create Human message and store in yaml format
        human = Human(name=name, ip=ip_num, shirt_color=colors, location='greet', action=get_action_len())
        store_human_info(human)

        respond = 'I got it, nice to meet you ' + name
        as_service.say(respond)

    return


def store_human_info(in_human):
    temp_human = Human(name=in_human.name,
                       ip=in_human.ip,
                       shirt_color=in_human.shirt_color.tolist(),
                       location=in_human.location,
                       action=in_human.action)

    human_dic = message_converter.convert_ros_message_to_dictionary(temp_human)  # transform into dictionary type

    f_name = rospkg.RosPack().get_path('thesis') + '/human_info/' + in_human.name + '.yaml'  # type: str
    with open(f_name, 'w') as f:
        yaml.dump(human_dic, f)

    return


def load_human_info(human_info_dir):
    """
    load human info for human identification.
    :return: A list of stored human beings.
    """

    yaml_list = os.listdir(human_info_dir)
    print 'Current human in dataset: ', yaml_list

    h_list = []

    if yaml_list is None:
        print 'No human in robot memory.'
    else:
        for f in yaml_list:
            temp = yaml.load(open(human_info_dir + f))
            temp_shirt_color = np.array(temp['shirt_color'])
            human_msg = message_converter.convert_dictionary_to_ros_message('thesis/Human', temp)
            human_msg.shirt_color = temp_shirt_color

            h_list.append(human_msg)

    return h_list


def get_action_len():
    config_dir = rospkg.RosPack().get_path('thesis') + '/config/'
    hand_acts = pd.read_csv(config_dir + 'hand_actions.csv', sep=',')  # DataFrame
    action_cat = hand_acts.columns.to_list()  # category of actions
    return len(action_cat)


if __name__ == '__main__':
    rospy.init_node('human_id', log_level=rospy.INFO)
    part_num = 18
    joints_features = [1, 2, 5]
    cv_bridge = CvBridge()

    # Naoqi setting
    if rospy.has_param("Pepper_ip"):
        pepper_ip = rospy.get_param("Pepper_ip")
    else:
        print 'Pepper_ip is not given'
        pepper_ip = '192.168.0.184'
    print 'Pepper_ip = ', pepper_ip

    session = qi.Session()

    try:
        session.connect("tcp://" + pepper_ip + ":" + str(9559))
    except RuntimeError:
        print("tcp://" + pepper_ip + "\"on port" + str(9559) + ".")
        print("Please check your script arguments. Run with -h option for help.")
        sys.exit(1)

    tts_service = session.service('ALTextToSpeech')
    tts_service.setLanguage('English')
    as_service = session.service("ALAnimatedSpeech")
    # End Naoqi setting

    rospy.loginfo('human_id start!')

    greet_msg = rospy.wait_for_message('/Tablet/voice', VoiceMessage)  # type: VoiceMessage
    print greet_msg
    if greet_msg.texts[0] == 'hello' or 'halo':
        greeting_cb()