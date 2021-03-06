import tensorflow as tf
import numpy as np
import tensorflow_probability as tfp
import trfl
import matplotlib.pyplot as plt
import D2D_env_discrete as D2D

writer = tf.summary.FileWriter("/home/stefan/tmp/D2D/2")

ch = D2D.Channel()

# set up Actor and Critic networks
class ActorCriticNetwork:
    def __init__(self, name, obs_size=2, action_size=2, actor_hidden_size=32, critic_hidden_size=32, ac_learning_rate=0.001,  
                 entropy_cost=0.01, normalise_entropy=True, lambda_=0., baseline_cost=1.):
    
        with tf.variable_scope(name):
            # network variables
            self.name=name
            self.input_ = tf.placeholder(tf.float32, [None, obs_size], name='inputs')
            self.action_ = tf.placeholder(tf.int32, [None, 1], name='action')
            self.reward_ = tf.placeholder(tf.float32, [None, 1], name='reward')
            self.discount_ = tf.placeholder(tf.float32, [None, 1], name='discount')
            self.bootstrap_ = tf.placeholder(tf.float32, [None], name='bootstrap')

            # set up actor network (approximates optimal policy)
            self.fc1_actor_ = tf.contrib.layers.fully_connected(self.input_, actor_hidden_size, activation_fn=tf.nn.elu)
            self.fc2_actor_ = tf.contrib.layers.fully_connected(self.fc1_actor_, actor_hidden_size, activation_fn=tf.nn.elu)
            self.fc3_actor_ = tf.contrib.layers.fully_connected(self.fc2_actor_, action_size, activation_fn=None)
            # reshape the policy logits
            self.policy_logits_ = tf.reshape(self.fc3_actor_, [-1, 1, action_size] )
  
            # generate action probabilities for taking actions
            self.action_prob_ = tf.nn.softmax(self.fc3_actor_)
      
            # set up critic network (approximates optimal state-value function (used as a baseline to reduce variance of loss gradient))
            # - uses policy evaluation (e.g. Monte-Carlo / TD learning) to estimate the advantage
            #self.fc1_critic1_ = tf.contrib.layers.fully_connected(self.input_, critic_hidden_size, activation_fn=tf.nn.elu)
            self.fc2_critic1_ = tf.contrib.layers.fully_connected(self.input_, critic_hidden_size, activation_fn=tf.nn.elu)
            self.baseline1_ = tf.contrib.layers.fully_connected(self.fc2_critic1_, 1, activation_fn=None)

            #self.fc1_critic2_ = tf.contrib.layers.fully_connected(self.input_, critic_hidden_size, activation_fn=tf.nn.elu)
            self.fc2_critic2_ = tf.contrib.layers.fully_connected(self.input_, critic_hidden_size, activation_fn=tf.nn.elu)
            self.baseline2_ = tf.contrib.layers.fully_connected(self.fc2_critic2_, 1, activation_fn=None)

            self.critic_reshape_ = tf.reshape([self.baseline1_, self.baseline2_], [-1, 2])

            #self.joint_baseline1_ = tf.contrib.layers.fully_connected(self.critic_reshape_, 32, activation_fn=tf.nn.elu)
            self.joint_baseline_ = tf.contrib.layers.fully_connected(self.critic_reshape_, 1, activation_fn=None)
      
            # Calculates the loss for an A2C update along a batch of trajectories. (TRFL)
            self.seq_aac_return_critic_1 = trfl.sequence_advantage_actor_critic_loss(self.policy_logits_, self.baseline1_, self.action_,
               self.reward_, self.discount_, self.bootstrap_, lambda_=lambda_, entropy_cost=entropy_cost, 
               baseline_cost=baseline_cost, normalise_entropy=normalise_entropy)

            self.seq_aac_return_critic_2 = trfl.sequence_advantage_actor_critic_loss(self.policy_logits_, self.baseline2_, self.action_,
               self.reward_, self.discount_, self.bootstrap_, lambda_=lambda_, entropy_cost=entropy_cost, 
               baseline_cost=baseline_cost, normalise_entropy=normalise_entropy)
      
            # Optimize the loss
            self.ac_loss_1 = tf.reduce_mean(self.seq_aac_return_critic_1.loss)
            self.ac_optim_1 = tf.train.AdamOptimizer(learning_rate=ac_learning_rate).minimize(self.ac_loss_1)

            self.ac_loss_2 = tf.reduce_mean(self.seq_aac_return_critic_2.loss)
            self.ac_optim_2 = tf.train.AdamOptimizer(learning_rate=ac_learning_rate).minimize(self.ac_loss_2)
      
    def get_network_variables(self):
        return [t for t in tf.trainable_variables() if t.name.startswith(self.name)]

# hyperparameters
max_timesteps = 5000  
discount = 0.99

actor_hidden_size = 32 # number of units per layer in actor net
critic_hidden_size = 32 # number of units per layer in critic net

ac_learning_rate = 0.005

baseline_cost = 10. #scale derivatives between actor and critic networks
#The `baseline_cost` parameter scales the
#  gradients w.r.t the baseline relative to the policy gradient. i.e:
#  `d(loss) / d(baseline) = baseline_cost * (n_step_return - baseline)`.

# entropy hyperparameters
entropy_cost = 0.001
normalise_entropy = True

# lambda_: an optional scalar or 2-D Tensor with shape `[T, B]` for
#        Generalised Advantage Estimation as per
#        https://arxiv.org/abs/1506.02438.
lambda_ = 0. # closer to 0 = TD like method - closer to 1 = Monte-Carlo like method

action_size = ch.n_actions
obs_size = ch.N_CU

print('action_size: ', action_size)
print('obs_size: ', obs_size)

D2D_nets = []
D2D_target_nets = []
D2D_target_net_update_ops = []

tf.reset_default_graph()

for i in range(0, ch.N_D2D):
    D2D_nets.append(ActorCriticNetwork(name='ac_net_{:.0f}'.format(i), obs_size=obs_size, action_size=action_size, actor_hidden_size=actor_hidden_size,
                                       ac_learning_rate=ac_learning_rate, entropy_cost=entropy_cost, normalise_entropy=normalise_entropy,
                                       lambda_=lambda_, baseline_cost=baseline_cost))

    print('Instantiated Network {:.0f} of {:.0f}'.format(i+1, ch.N_D2D))

    D2D_target_nets.append(ActorCriticNetwork(name='ac_target_net_{:.0f}'.format(i), obs_size=obs_size, action_size=action_size, actor_hidden_size=actor_hidden_size,
                                       ac_learning_rate=ac_learning_rate, entropy_cost=entropy_cost, normalise_entropy=normalise_entropy,
                                       lambda_=lambda_, baseline_cost=baseline_cost))

    print('Instantiated Target Network {:.0f} of {:.0f}'.format(i+1, ch.N_D2D))

    D2D_target_net_update_ops.append(trfl.update_target_variables(D2D_target_nets[i].get_network_variables(), 
                                                                  D2D_nets[i].get_network_variables(), tau=0.001))

    print('Instantiated Target Net Update ops {:.0f} of {:.0f}'.format(i+1, ch.N_D2D))
    print('\n')


stats_rewards_list = []
stats_every = 10

initial_actions = []
power_levels = []
RB_selections = []

g_iB, g_j, G_ij, g_jB, G_j_j = ch.reset()
    
state = np.zeros(ch.N_CU)

def running_mean(x, N):
    cumsum = np.cumsum(np.insert(x, 0, 0)) 
    return (cumsum[N:] - cumsum[:-N]) / N

with tf.Session() as sess:
    # Initialize variables
    sess.run(tf.global_variables_initializer())
    total_reward, t_length, done = 0, 0, 0
    stats_actor_loss, stats_critic_loss = 0., 0.
    total_loss_list_selfish, total_loss_list_selfless, action_list, action_prob_list, bootstrap_list = [], [], [], [], []
    rewards_list = []
    collision_var = 0

    # used for plots
    D2D_collision_probs = []
    collisions = []
    access_ratios = []
    access_rates = []
    avg_throughput = []
    time_avg_throughput = []

    for t in range(1, max_timesteps):

        ch.collision_indicator = 0
                     
        # generate action probabilities from policy net and sample from the action probs (policy)
        action_probs = []
        actions = []
        power_levels = []
        RB_selections = []

        for i in range(0, ch.N_D2D):
            action_probs.append(sess.run(D2D_nets[i].action_prob_, feed_dict={D2D_nets[i].input_: np.expand_dims(state,axis=0)}))
            action_probs[i] = action_probs[i][0]
            actions.append(np.random.choice(np.arange(len(action_probs[i])), p=action_probs[i]))
            power_levels.append(ch.action_space[actions[i]][0])
            RB_selections.append(ch.action_space[actions[i]][1])

        CU_SINR = ch.CU_SINR_no_collision(g_iB, power_levels, g_jB, RB_selections)
            
        next_state = ch.state(CU_SINR)
        D2D_SINR = ch.D2D_SINR_no_collision(power_levels, g_j, G_ij, G_j_j, RB_selections, next_state)
        reward, net, D2D_rewards, CU_reward = ch.D2D_reward_no_collision(D2D_SINR, CU_SINR, RB_selections)
            
        reward = reward / 10**10
        net = net / 10**10
        D2D_rewards = D2D_rewards / 10**10
        CU_reward = CU_reward / 10**10

        if ch.collision_indicator > 0:
            collision_var += 1
        
        collisions.append(ch.collision_indicator)
        
        D2D_collision_probs.append(collision_var / t)

        next_state = np.clip(next_state,-1.,1.)
        total_reward += net

        t_length += 1

        # bootstrapping: stopping to update many times in a trajectory
        #  - done by estimating the value of the current state using the critic net
        #
        # sutton - "updating the value estimate for a state
        #           from the estimated values of subsequent states" - given by critic net
        #
        #           "Only through bootstrapping do we introduce bias and 
        #            an asymptotic dependance on the quality of the
        #            function approximation" - this bias "often reduces variance
        #                                      and accelerates learning"

        # bootstrapping procedures (need to fix - bootstrapping happens once every timestep)
        if t == max_timesteps:
          bootstrap_value = np.zeros((1,),dtype=np.float32)
        else:
          #get bootstrap values
          bootstrap_values = []
          for i in range(0, ch.N_D2D):
            bootstrap_values.append(sess.run(D2D_target_nets[i].joint_baseline_, feed_dict={
                D2D_target_nets[i].input_: np.expand_dims(next_state, axis=0)}))
        
        # update network parameters
        total_losses_selfish = []
        seq_aac_returns_selfish = []

        total_losses_selfless = []
        seq_aac_returns_selfless = []

        for i in range(0, ch.N_D2D):
            #print(np.reshape(actions[i], (-1, 1)))

            #sess.run(tf.print("baseline vals: ", D2D_nets[i].joint_baseline_), feed_dict={
            #    D2D_nets[i].input_: np.expand_dims(state, axis=0)
            #})

            _, total_loss_selfish, seq_aac_return_selfish = sess.run([D2D_nets[i].ac_optim_1, D2D_nets[i].ac_loss_1, D2D_nets[i].seq_aac_return_critic_1], feed_dict={
                D2D_nets[i].input_: np.expand_dims(state, axis=0),
                D2D_nets[i].action_: np.reshape(actions[i], (-1, 1)),
                D2D_nets[i].reward_: np.reshape(D2D_rewards[i], (-1, 1)),
                D2D_nets[i].discount_: np.reshape(discount, (-1, 1)),
                D2D_nets[i].bootstrap_: np.reshape(bootstrap_values[i], (1,))
            })
            total_losses_selfish.append(total_loss_selfish)
            seq_aac_returns_selfish.append(seq_aac_return_selfish)

        for i in range(0, ch.N_D2D):
            #print(np.reshape(actions[i], (-1, 1)))
            _, total_loss_selfless, seq_aac_return_selfless = sess.run([D2D_nets[i].ac_optim_2, D2D_nets[i].ac_loss_2, D2D_nets[i].seq_aac_return_critic_2], feed_dict={
                D2D_nets[i].input_: np.expand_dims(state, axis=0),
                D2D_nets[i].action_: np.reshape(actions[i], (-1, 1)),
                D2D_nets[i].reward_: np.reshape(CU_reward, (-1, 1)),
                D2D_nets[i].discount_: np.reshape(discount, (-1, 1)),
                D2D_nets[i].bootstrap_: np.reshape(bootstrap_values[i], (1,))
            })
            total_losses_selfless.append(total_loss_selfless)
            seq_aac_returns_selfless.append(seq_aac_return_selfless)

        total_loss_list_selfish.append(np.mean(total_losses_selfish))
        total_loss_list_selfless.append(np.mean(total_losses_selfless))

        
        # update target network
        for i in range(0, ch.N_D2D):
            sess.run(D2D_target_net_update_ops[i])
        
        # debugging variables
        #stats_actor_loss += np.mean(seq_aac_return.extra.policy_gradient_loss)
        #stats_critic_loss += np.mean(seq_aac_return.extra.baseline_loss)
        action_list.append(actions)
        bootstrap_list.append(bootstrap_values)
        action_prob_list.append(action_probs)

        a = list(ch.accessed_CUs)
        if 2 in a:
            a = a.index(2)
            b = RB_selections.index(a)
        else:
            b = 0
        
        accessed = []
        throughput = []    
        for i in range(0, len(reward)):
            if reward[i] > 0:
                accessed.append(reward[i])
                throughput.append(reward[i])
            else:
                throughput.append(0.0)
        
        access_ratios.append(len(accessed) / len(reward))
        access_rates.append(sum(access_ratios) / t)

        avg_throughput.append(sum(throughput))
        time_avg_throughput.append(sum(avg_throughput)/ t)
        
        if t % stats_every == 0 or t == 1:
            print('Power Levels: ', power_levels)
            print('RB Selections: ', RB_selections)
            print('Rewards: ', reward)
            print('Accessed CUs: ', ch.accessed_CUs)
            print('Reward of colliding agent: ', reward[b])
            print('Number of Collisions: ', ch.collision_indicator)
            print('||(T)imestep): {}|| '.format(t),
                  'Last net (r)eward: {:.3f}| '.format(net),
                  'Selfless (L)oss: {:4f}|'.format(np.mean(total_loss_list_selfish)),
                  'Selfish (L)oss: {:4f}|'.format(np.mean(total_loss_list_selfless)))

        stats_rewards_list.append((t, total_reward, t_length))
        rewards_list.append(net)
        state = next_state

        #writer.add_graph(sess.graph)
        #print("Graph added!")
    ts, rews, lens = np.array(stats_rewards_list).T
    smoothed_rews = running_mean(rewards_list, 100)
    smoothed_col_probs = running_mean(D2D_collision_probs, 100)
    smoothed_access_rates = running_mean(access_rates, 100)
    smoothed_throughput = running_mean(time_avg_throughput, 100)

    reward_fig = plt.figure()

    plt.plot(ts[-len(smoothed_rews):], smoothed_rews)
    plt.plot(ts, rewards_list, color='grey', alpha=0.3)
    plt.xlabel('Time-slot')
    plt.ylabel('Reward')
    plt.show()

    collision_prob_fig = plt.figure()
    plt.ylim(0, 1)
    plt.xlim(0, 5000)
    plt.plot(ts[-len(smoothed_col_probs):], smoothed_col_probs)
    plt.plot(ts, D2D_collision_probs, color='grey', alpha=0.3)
    plt.xlabel('Time-slot')
    plt.ylabel('D2D collision probability')
    plt.show()

    true_collisions_fig = plt.figure()
    plt.ylim(0, 1)
    plt.xlim(0, 5000)
    plt.plot(ts, collisions)
    plt.ylabel('Number of collisions')
    plt.xlabel('Time-slot')
    plt.show()

    access_rate_fig = plt.figure()
    plt.ylim(0, 1)
    plt.xlim(0, 5000)
    plt.plot(ts[-len(smoothed_access_rates):], smoothed_access_rates)
    plt.plot(ts, access_rates, color='grey', alpha=0.3)
    plt.xlabel('Time-slot')
    plt.ylabel('D2D access rate')
    plt.show()

    time_avg_overall_thrghpt_fig = plt.figure()
    plt.plot(ts[-len(smoothed_throughput):], smoothed_throughput)
    plt.plot(ts, time_avg_throughput, color='grey', alpha=0.3)
    plt.xlabel('Time-slot')
    plt.ylabel('Time-averaged network throughput')
    plt.show()



