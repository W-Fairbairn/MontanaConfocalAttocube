import numpy as np
from qualang_tools.units import unit
from qualang_tools.plot import interrupt_on_close
from qualang_tools.results import progress_counter, fetching_tool
from qualang_tools.loops import from_array
from JM_set_octave import OctaveUnit, octave_declaration

# IQ imbalance matrix
def IQ_imbalance(g, phi):
    """
    Creates the correction matrix for the mixer imbalance caused by the gain and phase imbalances, more information can
    be seen here:
    https://docs.qualang.io/libs/examples/mixer-calibration/#non-ideal-mixer

    :param g: relative gain imbalance between the I & Q ports (unit-less). Set to 0 for no gain imbalance.
    :param phi: relative phase imbalance between the I & Q ports (radians). Set to 0 for no phase imbalance.
    """
    c = np.cos(phi)
    s = np.sin(phi)
    N = 1 / ((1 - g**2) * (2 * c**2 - 1))
    return [float(N * x) for x in [(1 - g) * c, (1 + g) * s, (1 - g) * s, (1 + g) * c]]


#############
# VARIABLES #
#############
u = unit(coerce_to_integer=True)
qop_ip = "192.168.88.254"
cluster_name = "Cluster_1"
qop_port = None  # Write the QOP port if version < QOP220
############################
# Set octave configuration #
############################
octave_port = 11235  # Must be 11xxx, where xxx are the last three digits of the Octave IP address
octave_1 = OctaveUnit("octave1", "192.168.88.233", port=80, con="con1")

# Add the octaves
octaves = [octave_1]
# Configure the Octaves
octave_config = octave_declaration(octaves)
octave = "octave1"

# Frequencies
NV_IF_freq = 40 * u.MHz
NV_LO_freq = 2.83 * u.GHz

# Pulses lengths
initialization_len_1 = 3000 * u.ns
refocusing_pause = 30000000 * u.ns
meas_len_1 = 364 * u.ns
long_meas_len_1 = 5000 * u.ns
initialization_len_2 = 3000 * u.ns
meas_len_2 = 364 * u.ns
long_meas_len_2 = 5000 * u.ns

# Relaxation time from the metastable state to the ground state after during initialization
relaxation_time = 300 * u.ns
wait_for_initialization = 5 * relaxation_time

# MW parameters
mw_amp_NV = 0.2  # in units of volts
mw_len_NV = 200 * u.ns

pi_amp_NV = 0.2  # in units of volts
pi_len_NV = 200 * u.ns

pi_half_amp_NV = pi_amp_NV / 2  # in units of volts
pi_half_len_NV = pi_len_NV / 2

# Readout parameters
signal_threshold_1 = -2_000  # ADC untis, to convert to volts divide by 4096 (12 bit ADC)
signal_threshold_2 = -2_000  # ADC untis, to convert to volts divide by 4096 (12 bit ADC)

# Delays
detection_delay_1 = 80 * u.ns
detection_delay_2 = 80 * u.ns
mw_delay = 0 * u.ns
laser_delay_1 = 87 * u.ns
laser_delay_2 = 87 * u.ns
wait_between_runs = 1500 * u.ns

config = {
    "version": 1,
    "controllers": {
        "con1": {
            "type": "opx1",
            "analog_outputs": {
                1: {"offset": 0.0, "delay": mw_delay},  # NV I
                2: {"offset": 0.0, "delay": mw_delay},  # NV Q
            },
            "digital_outputs": {
                1: {},  # AOM/Laser
                2: {},  # AOM/Laser
                3: {},  # SPCM1 - indicator
                4: {},  # SPCM2 - indicator
            },
            "analog_inputs": {
                1: {"offset": -0.03695245029296875, 'gain_db': -5},  # SPCM1},  # SPCM1
                2: {"offset": 0},  # SPCM2
            },
        }
    },

"octaves": {
        octave: {
            "RF_outputs": {
                1: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",  # can be external or internal. internal is the default
                    "output_mode": "triggered_reversed",  # can be: "always_on" / "always_off"/ "triggered" / "triggered_reversed". "always_off" is the default
                    "gain": 10,  # can be in the range [-20 : 0.5 : 20]dB
                },
                2: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                3: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                4: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
                5: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                    "output_mode": "always_on",
                    "gain": 0,
                },
            },
            "RF_inputs": {
                1: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",  # internal is the default
                    "IF_mode_I": "direct",  # can be: "direct" / "mixer" / "envelope" / "off". direct is default
                    "IF_mode_Q": "direct",
                },
                2: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "external",  # external is the default
                    "IF_mode_I": "direct",
                    "IF_mode_Q": "direct",
                },
            },
            "connectivity": "con1",
        }
    },
    "elements": {
        "NV": {
            "mixInputs": {"I": ("con1", 1), "Q": ("con1", 2), "lo_frequency": NV_LO_freq, "mixer": "mixer_NV"},
            "intermediate_frequency": NV_IF_freq,
            "operations": {
                "cw": "const_pulse",
                "x180": "x180_pulse",
                "x90": "x90_pulse",
                "-x90": "-x90_pulse",
                "-y90": "-y90_pulse",
                "-y90/5": "-y90/5_pulse",
                "-y90/2.5": "-y90/2.5_pulse",
                "y90": "y90_pulse",
                "y90/5": "y90/5_pulse",
                "y90/2.5": "y90/2.5_pulse",
                "y180": "y180_pulse",
            },
        },
        "AOM1": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 1),
                    "delay": laser_delay_1,
                    "buffer": 15
                },
            },
            "operations": {
                "laser_ON": "laser_ON_1",
                "laser_ON_refocusing": "laser_ON_refocusing"
            },
        },
        "AOM2": {
            "digitalInputs": {
                "marker": {
                    "port": ("con1", 2),
                    "delay": laser_delay_2,
                    "buffer": 15
                },
            },
            "operations": {
                "laser_ON": "laser_ON_2",
            },
        },
        "SPCM1": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "digitalInputs": {  # for visualization in simulation
                "marker": {
                    "port": ("con1", 3),
                    "delay": detection_delay_1,
                    "buffer": 15
                },
            },
            "operations": {
                "readout": "readout_pulse_1",
                "long_readout": "long_readout_pulse_1",
            },
            "outputs": {"out1": ("con1", 1)},
            "outputPulseParameters": {
                "signalThreshold": signal_threshold_1,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -2_000,
                "derivativePolarity": "Above",
            },
            "time_of_flight": detection_delay_1,
            "smearing": 0,
        },
        "SPCM2": {
            "singleInput": {"port": ("con1", 1)},  # not used
            "digitalInputs": {  # for visualization in simulation
                "marker": {
                    "port": ("con1", 4),
                    "delay": detection_delay_2,
                    "buffer": 15
                },
            },
            "operations": {
                "readout": "readout_pulse_2",
                "long_readout": "long_readout_pulse_2",
            },
            "outputs": {"out1": ("con1", 2)},
            "outputPulseParameters": {
                "signalThreshold": signal_threshold_2,  # ADC units
                "signalPolarity": "Below",
                "derivativeThreshold": -2_000,
                "derivativePolarity": "Above",
            },
            "time_of_flight": detection_delay_2,
            "smearing": 0,
        },
    },

    "pulses": {
        "const_pulse": {
            "operation": "control",
            "length": mw_len_NV,
            "waveforms": {"I": "cw_wf", "Q": "zero_wf"},
        },
        "x180_pulse": {
            "operation": "control",
            "length": pi_len_NV,
            "waveforms": {"I": "pi_wf", "Q": "zero_wf"},
        },
        "x90_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "pi_half_wf", "Q": "zero_wf"},
        },
        "-x90_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "minus_pi_half_wf", "Q": "zero_wf"},
        },
        "-y90_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "minus_pi_half_wf"},
        },

        "-y90/5_pulse": {
            "operation": "control",
            "length": pi_half_len_NV/5,
            "waveforms": {"I": "zero_wf", "Q": "minus_pi_half_wf"},
        },

        "-y90/2.5_pulse": {
            "operation": "control",
            "length": pi_half_len_NV/2.5,
            "waveforms": {"I": "zero_wf", "Q": "minus_pi_half_wf"},
        },

        "y90_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "pi_half_wf"},
        },

        "y90/5_pulse": {
            "operation": "control",
            "length": pi_half_len_NV/5,
            "waveforms": {"I": "zero_wf", "Q": "pi_half_wf"},
        },

        "y90/2.5_pulse": {
            "operation": "control",
            "length": pi_half_len_NV/2.5,
            "waveforms": {"I": "zero_wf", "Q": "pi_half_wf"},
        },

        "y180_pulse": {
            "operation": "control",
            "length": pi_half_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "pi_wf"},
        },

        "laser_ON_1": {
            "operation": "control",
            "length": initialization_len_1,
            "digital_marker": "ON",
        },
        "laser_ON_refocusing": {
            "operation": "control",
            "length": refocusing_pause,
            "digital_marker": "ON",
        },
        "laser_ON_2": {
            "operation": "control",
            "length": initialization_len_2,
            "digital_marker": "ON",
        },
        "readout_pulse_1": {
            "operation": "measurement",
            "length": meas_len_1,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "long_readout_pulse_1": {
            "operation": "measurement",
            "length": long_meas_len_1,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "readout_pulse_2": {
            "operation": "measurement",
            "length": meas_len_2,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
        "long_readout_pulse_2": {
            "operation": "measurement",
            "length": long_meas_len_2,
            "digital_marker": "ON",
            "waveforms": {"single": "zero_wf"},
        },
    },
    "waveforms": {
        "cw_wf": {"type": "constant", "sample": mw_amp_NV},
        "pi_wf": {"type": "constant", "sample": pi_amp_NV},
        "pi_half_wf": {"type": "constant", "sample": pi_half_amp_NV},
        "minus_pi_half_wf": {"type": "constant", "sample": (-1) * pi_half_amp_NV},
        "zero_wf": {"type": "constant", "sample": 0.0},
    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},  # [(on/off, ns)]
        "OFF": {"samples": [(0, 0)]},  # [(on/off, ns)]
    },
    "mixers": {
        "mixer_NV": [
            {"intermediate_frequency": NV_IF_freq, "lo_frequency": NV_LO_freq, "correction": IQ_imbalance(0.0, 0.0)},
        ],
    },
}
