#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Construct instructions based on human request and robot perception.
"""

import rospy

from thesis.msg import *

if __name__ == '__main__':
    rospy.init_node('instruction_constructor', anonymous=True, log_level=rospy.INFO)
    instr_pub = rospy.Publisher('/thesis/instruction_buffer', InstructionArray, queue_size=10, latch=True)
    rospy.loginfo('instruction_constructor start!')

    # initialize parameters
    loc_num = 6
    max_num = 3  # maximum number for simultaneous instructions in the period
    freq = 0.1  # 10 seconds
    des = range(loc_num)  # destination

    i_list = []  # i for 'instruction'
    # i_num = np.random.randint(max_num, dtype=int)

    for i in range(max_num):
        temp_i = Instruction(id=i, type=0, duration=3, source='Charlie', status=0,
                             function=0, target='Bob', destination=des[i % loc_num])
        i_list.append(temp_i)

    # print 'i_list = ', i_list
    instr_pub.publish(i_list)
    print 'publish instruction'
    rospy.spin()

    # rate = rospy.Rate(freq)
    # while not rospy.is_shutdown():
    #     i_list = []  # i for 'instruction'
    #     i_num = np.random.randint(max_num, dtype=int)
    #
    #     for i in range(i_num):
    #         i_loc = np.random.randint(loc_num)
    #         temp_i = Instruction(id=i, type=0, duration=30, location=i_loc, source='Ashe', status=0,
    #                              function=1, target='Bob', destination=des[i % loc_num])
    #         i_list.append(temp_i)
    #
    #     instr_pub.publish()
    #     rate.sleep()
