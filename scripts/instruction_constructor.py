#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Construct instructions based on human request and robot perception.
"""

import rospy
import rospkg
from jsk_gui_msgs.msg import VoiceMessage
from thesis.msg import *
from decision_making.node_viz import create_map_graph
from std_msgs.msg import Int8
import time
import random
import os
import argparse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from perception import human_id
import copy
import pandas as pd
from robot_motions import tts_service


class InstructionConstructor:
    def __init__(self):
        self.instr_sub = rospy.Subscriber('/thesis/instruction_buffer', InstructionArray, self.instr_cb, queue_size=10)
        self.verbal_sub = rospy.Subscriber('/Tablet/voice', VoiceMessage, self.verbal_cb, queue_size=10)
        self.temp_sub = rospy.Subscriber('/thesis/int_buffer', Int8, self.int_cb, queue_size=10)
        self._pkg_dir = rospkg.RosPack().get_path('thesis')

        self.instr_pub = rospy.Publisher('/thesis/instruction_buffer', InstructionArray, queue_size=1)
        self.map_graph = create_map_graph()
        self.instr_dict = dict()
        self.instr_dest_dict = {n: set() for n in self.map_graph.nodes}
        self.last_id = 0  # record the last id in current instruction buffer

        self.loc_symbol = {0: 'office', 1: 'bedroom', 2: 'charge', 3: 'alley1', 4: 'alley2',
                           5: 'livingroom', 6: 'diningroom', 7: 'greet', 8: 'emergency'}

        self.symptoms = {'fever', 'chill', 'headache', 'vomit', 'asthenia', 'dizziness', 'arthralgia', 'stomachache',
                         'diarrhea', 'thirst', 'spasm', 'restlessness', 'cough', 'dizziness', 'anorexia', 'sneeze',
                         'sore throat'}

        self.obj_set = {'tvmonitor', 'book', 'chair', 'laptop', 'mouse', 'cell phone', 'bed', 'sofa', 'book',
                        'pottedplant', 'tvmonitor', 'remote', 'diningtable', 'toaster', 'fork', 'bowl', 'spoon',
                        'knife', 'cup', 'bowl', 'chair'}

        trigger_words = [{'chat', 'talk'},  # chat, encourage
                         self.obj_set,  # remind object
                         {'schedule'},  # remind schedule
                         {'doing'},  # check human
                         {'music', 'song', 'video'},  # play music, video
                         {'game'},  # play game
                         self.symptoms,  # emergency
                         {'guest', 'guests'},  # guests
                         {'charge', 'charger'}]  # guests

        trigger_instr = [[1],
                         [2],
                         [3],
                         [4, 9],
                         [6],
                         [7],
                         [8],
                         [10],
                         [5]]

        self.verbal_instr = zip(trigger_words, trigger_instr)
        del trigger_words
        del trigger_instr

        self.analyser = SentimentIntensityAnalyzer()  # analyze human emotion sentiment

        # human_dict = {'name':{'Name': Human()}, 'ip':{'192.168.0.xxx':'Name'}}
        self.human_dict = human_id.load_human_info2dict(rospkg.RosPack().get_path('thesis') + '/human_info/')

        # ignore emergency tasks
        self.task_loc = [0, 1, 2, 5, 6, 7]
        # self.task_priority = range(1, 5)  # 1~4
        self.task_duration = range(1, 10)  # 1~9

        # scenario modeling
        # self.gamma_dict = {1: 1, 2: 2, 3: 5, 4: 8, 5: 10}  # {task_priority (emotion: 2, 3, 4): gamma}
        # self.gamma_dict = {1: 1, 2: 2, 3: 3, 4: 5, 5: 8}  # {task_priority (emotion: 2, 3, 4): gamma} to node 8
        self.gamma_dict = {1: 1, 2: 2, 3: 3, 4: 5, 5: 8}  # {task_priority (emotion: 2, 3, 4): gamma}
        self.b_dict = {1: 0.9, 2: 0.92, 3: 0.94, 4: 0.96, 5: 0.98}  # {task_priority (emotion: 2, 3, 4): beta}
        self.task_priority = sorted(self.gamma_dict.keys())
        self.dur_dict = {0: 3, 1: 5, 2: 8, 3: 8, 4: 15, 5: 10, 6: 15, 7: 30, 8: 60, 9: 10, 10: 60}  # {function: time(sec)}

    def instr_cb(self, in_instructions):
        rospy.logdebug('instruction callback')
        self.instr_dict = dict()

        # Convert InstructionArray into dictionary
        if type(in_instructions) == thesis.msg._InstructionArray.InstructionArray:

            for instr in in_instructions.data:
                self.instr_dest_dict[instr.destination].add(instr.id)
                self.instr_dict[instr.id] = instr

        rospy.logdebug('After instruction callback ...')
        self.show_instr()
        return

    def int_cb(self, in_int):
        self.instr_dict[self.last_id] = Instruction(id=self.last_id,
                                                    type=0,
                                                    duration=1,
                                                    source='Charlie',
                                                    status=0,
                                                    r=1,
                                                    b=0.9,
                                                    function=0,
                                                    target='Bob',
                                                    destination=in_int.data,
                                                    prev_id=-1,
                                                    start_time=time.time())
        self.last_id += 1

        self.launch_instr()
        return

    def show_instr(self):
        print '--------------------------------------------------------------------------'
        for key, instr in self.instr_dict.iteritems():
            print 'instr {0}: dest={1}, function={2}, duration={3}, r={4}'.format(instr.id,
                                                                                  instr.destination,
                                                                                  instr.function,
                                                                                  instr.duration,
                                                                                  instr.r)
        rospy.loginfo('Remaining tasks: {0}'.format(len(self.instr_dict)))
        print '--------------------------------------------------------------------------'
        return

    def verbal_cb(self, voice_data):
        def check_emotion(compound_score):
            """
            Convert emotion into status and reward
            :param compound_score: emotional sentiment score from vader
            :return: emotions (0:positive, 1:neutral, 2:negative), emotion+2 = task priority
            """
            if compound_score > 0.05:  # positive
                return 0
            elif -0.05 < compound_score < 0.05:  # neutral
                return 1
            elif compound_score < -0.05:  # negative
                return 2
            else:
                rospy.logerr('Invalid sentiment.')
                exit(1)

        if not rospy.get_param('/thesis/is_greeting', False):
            words = voice_data.texts[0].split()

            instr_source = human_id.identify_voice(self.human_dict['ip'], voice_data)
            emotion = check_emotion(self.analyser.polarity_scores(voice_data.texts[0])['compound'])

            # Check target of the instruction
            if instr_source == 'Alfred':
                instr_target = 'Alex'
            else:
                instr_target = None
                for w in words:
                    if w in self.human_dict['ip'].values():
                        instr_target = w

                if instr_target is None:
                    instr_target = instr_source

            last_id_buf = copy.copy(self.last_id)

            # Check function
            for w in words:
                for ver_i in self.verbal_instr:
                    if w in ver_i[0]:
                        print ver_i[1]

                        for i in range(len(ver_i[1])):
                            if ver_i[1][i] == 8:  # physical request
                                emotion = 3

                            if ver_i[1][i] == 9:  # report to source
                                temp_des = self.human_dict['name'][instr_source].location
                            elif ver_i[1][i] == 10:  # welcome guest
                                temp_des = 7
                            elif ver_i[1][i] == 5:
                                temp_des = 2
                            else:
                                temp_des = self.human_dict['name'][instr_target].location

                                # if instr_source == 'Alfred':
                                #     temp_des = 8
                                # else:
                                #     temp_des = self.human_dict['name'][instr_target].location

                            temp_instr = Instruction(id=self.last_id,
                                                     r=self.gamma_dict[emotion+2],
                                                     b=self.b_dict[emotion+2],
                                                     type=0,
                                                     duration=self.dur_dict[ver_i[1][i]],
                                                     source=instr_source,
                                                     status=emotion,
                                                     function=ver_i[1][i],
                                                     target=instr_target,
                                                     destination=temp_des,
                                                     start_time=time.time(),
                                                     prev_id=self.last_id-1 if i > 0 else -1)

                            self.instr_dict[temp_instr.id] = temp_instr
                            self.last_id += 1
            # if last_id_buf == self.last_id:  # NOP for not detecting key words
            #     temp_instr = Instruction(id=self.last_id,
            #                              r=self.gamma_dict[emotion+2],
            #                              b=self.b_dict[emotion+2],
            #                              type=0,
            #                              duration=self.dur_dict[0],
            #                              source=instr_source,
            #                              status=emotion,
            #                              function=0,
            #                              target=instr_target,
            #                              destination=self.human_dict['name'][instr_target].location,
            #                              prev_id=-1,
            #                              start_time=time.time())
            #     self.last_id += 1
            #     self.instr_dict[temp_instr.id] = temp_instr

            if len(self.instr_dict) > 0:
                tts_service.say('Ok, I got it.')
                self.launch_instr()
        return

    def launch_instr(self):
        rospy.loginfo('Launching instructions!')
        _instr_list = InstructionArray()
        for key, instr in self.instr_dict.iteritems():
            _instr_list.data.append(instr)

        # Update maximum instruction id
        # if len(self.instr_dict.keys()) > 0:
        #     self.last_id = max(self.instr_dict.keys())

        rospy.sleep(1)
        self.instr_pub.publish(_instr_list)
        return

    def save_instr(self):
        rospy.loginfo('Saving instructions')
        dir_name = self._pkg_dir + '/exp2/instr_' + str(args.max_num) + '_' + str(args.seed)

        if os.path.exists(dir_name):
            rospy.logdebug("Directory {0} already exists!".format(dir_name))
        else:
            os.makedirs(dir_name)
            rospy.logdebug("Directory {0} create!".format(dir_name))

        file_name = dir_name + '/' + 'instr.csv'

        in_id = list()
        in_des_ls = list()
        in_r_list = list()
        in_b_list = list()
        in_d_list = list()

        for _, instr in self.instr_dict.iteritems():
            in_id.append(instr.id)
            in_des_ls.append(instr.destination)
            in_r_list.append(instr.r)
            in_b_list.append(instr.b)
            in_d_list.append(instr.duration)

        output_df = pd.DataFrame({'id': in_id,
                                  'destination': in_des_ls,
                                  'gamma': in_r_list,
                                  'beta': in_b_list,
                                  'duration': in_d_list})

        output_df.to_csv(file_name, index=False, columns=['id', 'destination', 'gamma', 'beta', 'duration'])
        rospy.loginfo('Done!')
        return

    def test_scenario(self):
        if is_random:  # for random generate tasks
            random.seed(int(args.seed))
            max_num = args.max_num
            des_ls = [random.choice(self.task_loc) for _ in range(max_num)]  # destination
            priority_list = [random.choice(self.task_priority) for _ in range(max_num)]  # reward list
            d_list = [random.choice(self.task_duration) for _ in range(max_num)]  # duration list

        else:
            # des_ls = [0, 5, 5, 0, 7, 2, 1, 6, 2, 7, 2, 6, 1, 6, 0, 6, 5]  # destination
            # priority_list = [2, 2, 1, 2, 1, 3, 2, 2, 2, 3, 1, 4, 1, 2, 4, 1, 4]  # reward
            # d_list = [9, 2, 8, 3, 6, 9, 3, 7, 3, 8, 5, 7, 9, 1, 6, 5, 9]  # duration

            _test_instr = [(2, 3, 2), (2, 5, 15), (0, 1, 1), (1, 1, 3), (0, 2, 10),
                           (6, 3, 3), (5, 1, 10), (6, 4, 6), (7, 2, 2), (6, 5, 15)]  # (dest, priority, duration)

            # _test_instr = [(0, 1, 1), (1, 1, 3), (5, 1, 10)]  # (dest, priority, duration)
            # _test_instr = [(6, 5, 3), (0, 1, 2)]  # (dest, priority, duration)
            # _test_instr = [(0, 1, 2)]  # (dest, priority, duration)

            des_ls = list()
            priority_list = list()
            d_list = list()

            for instr in _test_instr:
                des_ls.append(instr[0])
                priority_list.append(instr[1])
                d_list.append(instr[2])

            max_num = len(des_ls)

        for i in range(max_num):
            temp_i = Instruction(id=self.last_id, type=0, duration=d_list[i], source='Charlie', status=0,
                                 r=self.gamma_dict[priority_list[i]], b=self.b_dict[priority_list[i]],
                                 function=0, target='Bob', destination=des_ls[i], prev_id=-1, start_time=time.time())
            self.instr_dict[self.last_id] = temp_i
            self.last_id += 1

        rospy.loginfo('Total task duration: {0} (s)'.format(sum(d_list)))
        self.save_instr()  # for experiment evaluation

        t = 1
        rospy.loginfo('Sleep for {0} seconds'.format(str(t)))
        rospy.sleep(t)

        start_time = time.time()
        rospy.set_param('/instr_start_time', start_time)
        self.launch_instr()
        rospy.sleep(t)

        while not rospy.is_shutdown():
            try:
                temp_instr = rospy.wait_for_message('/thesis/instruction_buffer', InstructionArray, timeout=0.5)
                if len(temp_instr.data) == 0:
                    end_time = time.time()
                    rospy.loginfo('Task duration: {0} (s)'.format(sum(d_list)))
                    rospy.loginfo('Total process time: {0} (s)'.format(end_time - start_time - t))
                    rospy.loginfo('Navigation process time: {0} (s)'.format(end_time - start_time - t - sum(d_list)))
                    break

            except rospy.ROSException:  # timeout
                pass

        return

    def run(self):
        time.sleep(3)
        tts_service.say('Oh, time to remind Bob his schedule.')
        temp_init = Instruction(id=self.last_id, type=1, duration=5, source=None, status=2,
                             r=self.gamma_dict[1], b=self.b_dict[1],
                             function=3, target='Bob', destination=5, prev_id=-1, start_time=time.time())
        self.instr_dict[self.last_id] = temp_init
        self.last_id += 1

        t = 1
        rospy.loginfo('Sleep for {0} seconds'.format(str(t)))
        rospy.sleep(t)

        start_time = time.time()
        rospy.set_param('/instr_start_time', start_time)
        self.launch_instr()
        rospy.sleep(t)

        while not rospy.is_shutdown():
            try:
                self.show_instr()
            except rospy.ROSException:  # timeout
                pass
            time.sleep(0.5)

        # rospy.sleep(40)
        # for i in range(2):
        #     temp_i = Instruction(id=self.last_id, type=0, duration=60, source='Eric', status=0,
        #                          r=self.gamma_dict[priority_list[i]], b=self.b_dict[priority_list[i]],
        #                          function=0, target='Bob', destination=des_ls[i], prev_id=-1, start_time=time.time())
        #     self.instr_dict[self.last_id] = temp_i
        #     self.last_id += 1

        return


if __name__ == '__main__':
    rospy.init_node(os.path.basename(__file__).split('.')[0], log_level=rospy.INFO)
    parser = argparse.ArgumentParser(description='Check roslaunch arg')
    parser.add_argument('--max_num', type=int, default=10)
    parser.add_argument('--is_rand', type=int, default=1)
    parser.add_argument('--is_sim', type=int, default=0)
    parser.add_argument('--seed', type=int, default=1111)
    args = parser.parse_args(rospy.myargv()[1:])

    if args.is_rand == 1:
        is_random = True
    elif args.is_rand == 0:
        is_random = False
    else:
        rospy.logerr('is_rand only supports 0 or 1.')
        exit(1)

    instr_constructor = InstructionConstructor()

    if args.is_sim == 0:
        instr_constructor.run()
    elif args.is_sim == 1:
        rospy.set_param('/thesis/seed', args.seed)
        rospy.set_param('/thesis/max_num', args.max_num)
        rospy.sleep(0.2)

        # This is for accumulative reward curve
        rospy.loginfo('Waiting for /thesis/init_tmp ...')
        while not rospy.get_param('/thesis/init_tmp', False):
            pass
        # end
        instr_constructor.test_scenario()

    else:
        rospy.logerr('is_sim only supports 0 or 1.')
        exit(1)
