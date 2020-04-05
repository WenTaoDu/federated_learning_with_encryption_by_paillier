import numpy as np
from sklearn.datasets import load_diabetes

import phe as paillier

seed = 42
np.random.seed(seed)
pubkey, privkey = paillier.generate_paillier_keypair(n_length=1024)


def encrypt_vector(pubkey, x):
    return [pubkey.encrypt(x[i]) for i in range(x.shape[0])]


def decrypt_vector(privkey, x):
    return np.array([privkey.decrypt(i) for i in x])


def sum_encrypted_vectors(x, y):
    if len(x) != len(y):
        raise Exception('Encrypted vectors must have the same size')

    return [x[i] + y[i] for i in range(len(x))]


def mean_square_error(y_pred, y):
    return np.mean((y - y_pred) ** 2)


def get_data(n_clients):
    diabetes = load_diabetes()
    y = diabetes.target
    X = diabetes.data

    # Add constant to emulate intercept
    X = np.c_[X, np.ones(X.shape[0])]

    # The features are already preprocessed
    # Shuffle
    perm = np.random.permutation(X.shape[0])
    X, y = X[perm, :], y[perm]

    # Select test at random
    test_size = 50
    test_idx = np.random.choice(X.shape[0], size=test_size, replace=False)
    train_idx = np.ones(X.shape[0], dtype=bool)
    train_idx[test_idx] = False

    X_test, y_test = X[test_idx, :], y[test_idx]
    X_train, y_train = X[train_idx, :], y[train_idx]

    # Split train among multiple clients.
    # The selection is not at random. We simulate the fact that each client
    # sees a potentially very different sample of patients.
    X, y = [], []
    step = int(X_train.shape[0] / n_clients)

    for c in range(n_clients):
        X.append(X_train[step * c: step * (c + 1), :])
        y.append(y_train[step * c: step * (c + 1)])

    # X[0] shape 130*11; y[0] shape 130
    return X, y, X_test, y_test


class Server:
    """Hold the private key. Decrypt the average gradient"""

    def __init__(self, key_length=1024):
        self.pubkey, self.privkey = \
            paillier.generate_paillier_keypair(n_length=key_length)

    def decrypt_aggregate(self, input_model, n_clients):
        return decrypt_vector(self.privkey, input_model) / n_clients


class Client:
    """Run linear regression either with local data or by gradient steps,
    where gradients can be send from remotely.
    Hold the private key and can encrypt gradients to send remotely.
    """

    def __init__(self, name, X, y, pubkey):
        self.name = name
        self.pubkey = pubkey
        self.X, self.y = X, y
        self.weights = np.zeros(X.shape[1])

    def fit(self, n_iter, eta=0.01):
        """Linear regression for n_iter"""

        for _ in range(n_iter):
            gradient = self.compute_gradient()
            self.gradient_step(gradient, eta)

    def gradient_step(self, gradient, eta=0.01):
        """Update the model with the given gradient"""

        self.weights -= eta * gradient

    def compute_gradient(self):
        """Return the gradient computed at the current model on all training
        set"""

        delta = self.predict(self.X) - self.y
        return delta.dot(self.X)

    def predict(self, X):
        """Score test data"""
        return X.dot(self.weights)

    def encrypted_gradient(self, sum_to=None):
        """Compute gradient. Encrypt it.
        When `sum_to` is given, sum the encrypted gradient to it, assumed
        to be another vector of the same size
        """

        gradient = encrypt_vector(self.pubkey, self.compute_gradient())

        if sum_to is not None:
            if len(sum_to) != len(gradient):
                raise Exception('Encrypted vectors must have the same size')
            return sum_encrypted_vectors(sum_to, gradient)
        else:
            return gradient


n_iter, eta = 50, 0.01
names = ['Hospital 1', 'Hospital 2', 'Hospital 3']
n_clients = len(names)
X, y, X_test, y_test = get_data(n_clients=n_clients)

server = Server(key_length=1024)
clients = []
for i in range(n_clients):
    clients.append(Client(names[i], X[i], y[i], server.pubkey))

for c in clients:
    c.fit(n_iter, eta)
    y_pred = c.predict(X_test)
    print('{:s}:\t{:.2f}'.format(c.name, mean_square_error(y_pred, y_test)))

for i in range(n_iter):
    # Compute gradients, encrypt and aggregate
    encrypt_aggr = clients[0].encrypted_gradient(sum_to=None)
    for i in range(1, n_clients):
        encrypt_aggr = clients[i].encrypted_gradient(sum_to=encrypt_aggr)

    # Send aggregate to server and decrypt it
    aggr = server.decrypt_aggregate(encrypt_aggr, n_clients)

    # Take gradient steps
    for c in clients:
        c.gradient_step(aggr, eta)

for c in clients:
    y_pred = c.predict(X_test)
    print('{:s}:\t{:.2f}'.format(c.name, mean_square_error(y_pred, y_test)))
