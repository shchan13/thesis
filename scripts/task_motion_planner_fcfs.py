#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Solve task planning with first come first serve
"""

from perception.human_id import *
from thesis.msg import *
import rospkg
from std_msgs.msg import String
from decision_making.node_viz import create_map_graph
import numpy as np
import networkx as nx


class TaskMotionPlannerFCFS:
    def __init__(self):
        self.sub = rospy.Subscriber('/thesis/instruction_buffer', InstructionArray, self.plan_task, queue_size=5)
        self.task_pub = rospy.Publisher('/thesis/instruction_buffer', InstructionArray, queue_size=1)

        # for two-stage instruction ('check status' from caregiver)
        # human_dict = {'name':{'Name': Human()}, 'ip':{'192.168.0.xxx':'Name'}}
        self.human_dict = load_human_info2dict(rospkg.RosPack().get_path('thesis') + '/human_info/')

        # for TAMP
        self.map_graph = create_map_graph()
        self.adjacency_matrix = nx.convert_matrix.to_numpy_array(self.map_graph)
        self.cur_node = 2  # initial at charge, type=int
        self.next_node = self.cur_node  # initial at charge, type=int
        self.time_step = rospy.get_param('/thesis/time_step', 1.0)
        self.sim_time_step = 2.0
        self.instr_dict = dict()
        self.instr_dest_dict = {n: set() for n in self.map_graph.nodes}

        # reset everything for demo
        rospy.set_param('/thesis/face_track', False)
        rospy.set_param('/thesis/use_openpose', False)
        rospy.set_param('/thesis/action_on', False)
        rospy.set_param('/thesis/next_node', -1)
        rospy.set_param('/thesis/is_greeting', False)
        rospy.set_param('/thesis/reach', False)
        # end

        # for visualization, including nodes and edges
        self.viz_node_pub = rospy.Publisher('/thesis/robot_node', String, queue_size=2)
        self._pkg_dir = rospkg.RosPack().get_path('thesis')
        self.cur_neighbor = self.adjacency_matrix[self.cur_node].astype(int).tolist()

        # for experiment evaluations
        self.plan_time = 0.0
        self.accu_r = 0.0  # accumulate reward
        self.accu_r_list = [0.0]
        self.time_r_list = [0.0]
        self.save_csv_flag = False
        self.done_instr = list()
        self.max_num = int(rospy.get_param('/thesis/max_num', 10))
        self.seed = int(rospy.get_param('/thesis/seed', 1111))
        self.base_name = os.path.basename(__file__).split('.')[0]
        rospy.set_param('/thesis/init_tmp', True)
        # end

    def show_instr(self):
        _loc_symbol = {0: 'office',
                       1: 'bedroom',
                       2: 'charge',
                       3: 'alley1',
                       4: 'alley2',
                       5: 'livingroom',
                       6: 'diningroom',
                       7: 'greet',
                       8: 'emergency'}

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

    def get_pkg_dir(self):
        print 'pkg path', self._pkg_dir
        return

    def plan_task(self, in_instructions):
        rospy.loginfo('Planning task ...')
        # self.cur_instr.data = list(instr_list.data)

        # Convert InstructionArray into dictionary
        if type(in_instructions) == thesis.msg._InstructionArray.InstructionArray:
            for instr in in_instructions.data:
                self.instr_dest_dict[instr.destination].add(instr.id)
                self.instr_dict[instr.id] = instr

        self.show_instr()

        # Fetch the destination from the task
        if len(self.instr_dict.keys()) > 0:
            dest_node = self.instr_dict[min(self.instr_dict.keys())].destination  # destination node
            rospy.loginfo('destination node: {0}'.format(dest_node))
            temp_path = nx.shortest_path(self.map_graph, self.cur_node, dest_node, weight='weight')
            rospy.loginfo('temp_path = {0}'.format(temp_path))

            if len(temp_path) > 1:
                self.next_node = temp_path[1]  # next neighbor node for motion planner
            else:
                self.next_node = self.cur_node
            rospy.loginfo('plan_task result: {0}'.format(self.next_node))

        return

    def move_adjacency_node(self, dest_neighbor_node, sim=True, render=False, in_node=None):
        """
        Get the neighbor of next node after moving.
        :param dest_neighbor_node: int of neighbor node
        :param sim: is it simulation or real move
        :param render: Whether to show on networkx.
        :param in_node: input_node, usually cur_node
        :return: next_neighbor, type=list()
        """

        rospy.logdebug('move_adjacency_node, in_node: {0}'.format(in_node))
        # rospy.loginfo('cur_neighbor = {0}'.format(self.cur_neighbor))

        if in_node is None:
            in_node = self.cur_node
            _temp_neighbor = list(self.cur_neighbor)  # copy the list, not changing self.cur_neighbor
        else:
            _temp_neighbor = list(self.adjacency_matrix[in_node].astype(int).tolist())  # copy the list

        _neighbor_nodes = np.where(np.array(_temp_neighbor) > 0)[0].tolist()

        rospy.logdebug('dest_neighbor_node = {0}'.format(dest_neighbor_node))
        rospy.logdebug('_neighbor_nodes = {0}'.format(_neighbor_nodes))

        if dest_neighbor_node == in_node:
            rospy.loginfo('dest_node is the same as in_node {0}'.format(in_node))
            return _temp_neighbor

        elif dest_neighbor_node not in _neighbor_nodes:
            rospy.logerr('Error in task_motion_planner_fcfs.py: Invalid destination for planning.')
            exit(1)

        # update neighbor after moving
        for n in _neighbor_nodes:
            if n == dest_neighbor_node:  # moving toward desire neighbor node
                _temp_neighbor[n] -= 1

                if _temp_neighbor[n] == 0:  # robot reaches the desire neighbor node
                    _temp_neighbor = np.copy(self.adjacency_matrix[n]).astype(int).tolist()
                    break

                _temp_neighbor[in_node] += 1

            elif n == in_node:  # robot is currently on the edge.
                continue

            else:
                _temp_neighbor[n] = 0

        if not sim:  # if real move, not checking the candidate steps.
            self.cur_neighbor = list(_temp_neighbor)
            # rospy.loginfo('self.cur_neighbor: {0}'.format(self.cur_neighbor))

            if render:
                # robot reach destination neighbor node
                if self.cur_neighbor == self.adjacency_matrix[dest_neighbor_node].astype(int).tolist():
                    self.cur_node = dest_neighbor_node
                    _robot_node = str(self.cur_node)

                # robot is on edge
                else:
                    _nodes_on_edge = sorted([self.cur_node, dest_neighbor_node])
                    _temp_step = self.cur_neighbor[_nodes_on_edge[0]]
                    _nodes_on_edge = map(str, _nodes_on_edge)
                    _robot_node = ''
                    for e in _nodes_on_edge:
                        _robot_node += e
                    _robot_node += '_'
                    _robot_node += str(_temp_step)

                # rospy.loginfo('robot_node = {0}'.format(_robot_node))

                # Publish the robot node in str type
                _viz_node = String()
                _viz_node.data = str(_robot_node)
                self.viz_node_pub.publish(_viz_node)

        rospy.logdebug('neighbor array after moving: {0}'.format(_temp_neighbor))
        return _temp_neighbor

    def plan_motion_viz(self):
        if self.cur_node == self.next_node:
            rospy.loginfo('Motion: Reach node {0}.'.format(self.next_node))
            # if self.cur_node in self.instr_dest_dict.keys():
            if len(self.instr_dest_dict[self.cur_node]) > 0:
                # This is for FCFS!!!
                for idx in self.instr_dest_dict[self.cur_node]:
                    if idx == min(self.instr_dict.keys()):
                        do_instr = self.instr_dict[idx]
                        rospy.loginfo('Do instr {0}: {1}'.format(idx, do_instr.function))
                        rospy.sleep(do_instr.duration)

                        del self.instr_dict[do_instr.id]
                        self.instr_dest_dict[self.cur_node].remove(do_instr.id)

                        break

                # Convert undo_tasks to a list() and publish to /thesis/instruction_buffer
                undo_instr_list = list()
                for key, value in self.instr_dict.iteritems():
                    undo_instr_list.append(value)

                self.task_pub.publish(undo_instr_list)

            else:
                rospy.loginfo('No instructions on task {0}'.format(self.cur_node))
                if len(self.instr_dict) > 0:
                    self.plan_task(self.instr_dict)

        else:
            rospy.loginfo('Motion: from {0} to {1}'.format(self.cur_node, self.next_node))
            self.move_adjacency_node(self.next_node, sim=False, render=True)

        return

    def cal_accu_reward(self, input_instr):
        # calculate obtained reward
        # rospy.set_param('instr_start_time') is in "instruction_constructor.py"
        _temp_step = (time.time() - rospy.get_param('/instr_start_time')) / self.sim_time_step
        self.accu_r += input_instr.r * (input_instr.b ** _temp_step)
        self.accu_r_list.append(self.accu_r)
        self.time_r_list.append(_temp_step)
        rospy.logdebug('accu reward: {0}'.format(self.accu_r))

        return

    def save_accu_reward(self, time_list=None, r_list=None, csv_name=None):
        rospy.loginfo('Saving accumulative reward')

        if time_list is None:
            time_list = self.time_r_list
        if r_list is None:
            r_list = self.accu_r_list
        if csv_name is None:
            csv_name = self.base_name+'_reward.csv'

        csv_file = self._pkg_dir + '/exp2/instr_' + str(self.max_num) + '_' + str(self.seed) + '/' + csv_name
        output_df = pd.DataFrame({'time': time_list, 'reward': r_list})
        output_df.to_csv(csv_file, index=False, columns=['time', 'reward'])

        rospy.sleep(1)
        rospy.loginfo('Save to: {0}'.format(csv_file))
        rospy.loginfo('Done!')
        return

    def save_done_instr_id(self, id_seq=None, csv_name=None):
        rospy.loginfo('Save done instructions')

        if id_seq is None:
            id_seq = self.done_instr
        if csv_name is None:
            csv_name = self.base_name+'_done.csv'

        rospy.loginfo('done_instr: {0}'.format(id_seq))
        csv_file = self._pkg_dir + '/exp2/instr_' + str(self.max_num) + '_' + str(self.seed) + '/' + csv_name
        output_df = pd.DataFrame({'done': id_seq})
        output_df.to_csv(csv_file, index=False)

        rospy.sleep(1)
        rospy.loginfo('Save to: {0}'.format(csv_file))
        rospy.loginfo('Done!')
        return

    def run_plan_viz(self):
        rospy.loginfo('Start TAMP!')

        # Publish the initial position node of the robot to visualization
        rospy.sleep(0.5)
        self.viz_node_pub.publish(String(data=str(self.cur_node)))

        # Start running motion planning and visualization
        rate = rospy.Rate(1.0 / self.sim_time_step)
        while not rospy.is_shutdown():
            self.plan_motion_viz()
            rate.sleep()

        return


if __name__ == '__main__':
    rospy.init_node(os.path.basename(__file__).split('.')[0], log_level=rospy.INFO)
    tamp = TaskMotionPlannerFCFS()
    tamp.run_plan_viz()
