import tensorflow as tf
import numpy as np
from src import config, noise, replaybuffer, environment, util
from agent import model, ddpgagent
import matplotlib.pyplot as plt
import h5py
import math
from src.config import Config
import os
import random
import logging

import warnings

def run(conf=None, actors=None, path_timestamp=None, out=None, step_bound=None, const_bound=None, ramp_bound=None, root_path=None, seed=True, pl_idx=None):
    log = logging.getLogger(__name__)
    if conf is None:
        conf_path = os.path.join(root_path, config.Config.param_path)
        log.info(f"Loading configuration instance from {conf_path}")
        conf = util.config_loader(conf_path)
    
    if path_timestamp is None:
        model_parent_dir = root_path
    else:
        model_parent_dir = path_timestamp
    
    if seed:
        np.random.seed(conf.evaluation_seed)
        tf.random.set_seed(conf.evaluation_seed)
        os.environ['PYTHONHASHSEED']=str(conf.evaluation_seed)
        random.seed(conf.evaluation_seed)

    env = environment.Platoon(conf.pl_size, conf, rand_states=False) # do not use random states here, for consistency across evaluation sessions
    num_models = env.num_models
    if actors is None:
        actors = []
        for m in range(num_models):
            tag = conf.img_tag % (p+1, m+1)
            actors.append(tf.keras.models.load_model(os.path.join(root_path, conf.actor_fname % (tag)), compile=False))

    input_opts = {conf.guasfig_name : [util.get_random_val(conf.rand_gen, conf.reset_max_u, std_dev=conf.reset_max_u, config=conf)
                                        for _ in range(conf.steps_per_episode)]}

    actions = np.zeros((num_models, env.num_actions))
    pl_states = np.zeros((conf.steps_per_episode, conf.pl_size, env.def_num_states))
    pl_inputs = np.zeros((conf.steps_per_episode, conf.pl_size, env.def_num_actions))

    num_rows = env.def_num_states + 1
    num_cols = 1
    episodic_reward_counters = np.array([0]*num_models, dtype=np.float32)
    for typ, input_list in input_opts.items():
        fig, axs = plt.subplots(num_rows,num_cols, figsize = (4,12))
        states = env.reset()
        for i in range(conf.steps_per_episode):
            if conf.show_env == True:
                env.render()
                
            for m in range(num_models):
                state = tf.expand_dims(tf.convert_to_tensor(states[m]), 0)
                actions[m] = ddpgagent.policy(actors[m](state), lbound=conf.action_low, hbound=conf.action_high)[0] # do not use noise in the simulation
    
            states, rewards, terminal = env.step(actions.flatten(), input_list[i])

            for m in range(num_models):
                episodic_reward_counters[m] += rewards[m]
                pl_states[i] = np.reshape(states, (conf.pl_size, env.def_num_states)) # reshapes to standard format, regardless of cent or decent
                pl_inputs[i] = np.reshape(actions, (conf.pl_size, env.def_num_actions))
            
        for i in range(conf.pl_size): # for each follower's states in the platoon states
            for j in range(env.def_num_states): # state plots
                axs[j].plot(pl_states[:,i][:,j], label=f"Vehicle {i+1}")
                axs[j].xaxis.set_label_text(f"{conf.sample_rate}s steps (total time of {conf.episode_sim_time} s)")
                axs[j].yaxis.set_label_text(f"{env.state_lbs[j]}")
                axs[j].legend()
            
            axs[num_rows-1].plot(pl_inputs[:, i], label=f"Vehicle {i+1}") # input plots

        axs[num_rows-1].plot(input_list, label=f"Platoon leader") # overlay platoon leaders transmitted data
        axs[num_rows-1].xaxis.set_label_text(f"{conf.sample_rate}s steps (total time of {conf.episode_sim_time} s)")
        axs[num_rows-1].yaxis.set_label_text("u")
        axs[num_rows-1].legend()
        pl_rew = round(np.average(episodic_reward_counters), 3)

        pl_title = f"{conf.model} {typ} input response\n with cumulative platoon reward of %.3f\n and random seed %s" % (pl_rew, conf.evaluation_seed)
        if len(episodic_reward_counters) == 1:
            plt.suptitle(pl_title)
        else:
            plt.suptitle(pl_title + f"and cumulative vehicle rewards {np.round(episodic_reward_counters, 2)}")
        plt.tight_layout()

        if out == 'save':
            out_file = os.path.join(model_parent_dir, f"res_{typ}{conf.pl_tag % (pl_idx)}.png")
            log.info(f"Generated {typ} simulation plot to -> {out_file}")
            plt.savefig(out_file)
        else:
            
            plt.show()
    
    return pl_rew