"""
Octave configuration working for QOP222 and qm-qua==1.1.5 and newer.
"""

from set_octave import OctaveUnit, octave_declaration
import os
from qualang_tools.units import unit
from qualang_tools.loops import from_array
from qualang_tools.results import fetching_tool, progress_counter
from qualang_tools.plot import interrupt_on_close
from pathlib import Path
import numpy as np
import plotly.io as pio


from qm import QuantumMachinesManager

u = unit(coerce_to_integer=True)

######################
# Network parameters #
######################
qop_ip = "192.168.88.252"  # Write the QM router IP address
cluster_name = "Fresh_Gopher"  # Write your cluster_name if version >= QOP220
qop_port = None  # Write the QOP port if version < QOP220

############################
# Set octave configuration #
############################
octave = "oct1"
octave_port = (
    11251  # Must be 11xxx, where xxx are the last three digits of the Octave IP address
)
octave_1 = OctaveUnit("octave1", "192.168.88.251", port=octave_port, con="con1")

# Add the octaves
# octaves = [octave_1]
# Configure the Octaves
# octave_config = octave_declaration(octaves)

#####################
# OPX configuration #
#####################

power_amp_calibration = {
    -40: 0,
    -12: 0.01,
    -2: 0.05,
    10: 0.2,
    18: 0.5,
    22: 0.75,
    24: 1.0,
}


# Directory that contains QM/calibration_db.json (used by QuantumMachinesManager)
calibration_db_dir = "/home/cjs/Documents/OPXEnv/Qudi-Core_With_IQO_Modules/OPXFiles/opx_gui"

#####################################
#  Shared QuantumMachinesManager    #
#####################################
# Every experiment class used to construct its own QuantumMachinesManager
# (in __init__ or compile_program(), i.e. on every Run click, or for
# T1/HBT every time the experiment dropdown was switched to them) and
# never closed it. Each construction performs a real network handshake
# (detect_server() against the OPX gateway on port 80) and holds open a
# live connection; repeatedly creating and abandoning these exhausts the
# gateway's connection handling and causes intermittent "Failed to detect
# to QuantumMachines server" errors that only clear up once old
# connections eventually time out - matching "have to keep trying over
# and over". Constructed lazily here (not at import time, so the app can
# still start even if the OPX is briefly unreachable) and shared for the
# rest of the process via get_qmm().
_qmm = None


def get_qmm():
    """Return the shared QuantumMachinesManager, creating it on first use."""
    global _qmm
    if _qmm is None:
        _qmm = QuantumMachinesManager(
            host=qop_ip,
            cluster_name=cluster_name,
            octave_calibration_db_path=calibration_db_dir,
        )
    return _qmm

#############
# Save Path #
#############
# Path to save data

save_dir = "/home/cjs/Documents/ConfocalData"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)


# Frequencies
NV_IF_freq = 50 * u.MHz
NV_LO_freq = 2.65 * u.GHz

refocus_len = 30000 * u.ns
# Pulses lengths
initialization_len_1 = 3500 * u.ns
meas_len_1 = 500 * u.ns
long_meas_len_1 = 8000 * u.ns

initialization_len_2 = 3500 * u.ns
meas_len_2 = 500 * u.ns
long_meas_len_2 = 8000 * u.ns

# T1 with Rf
"""
wait time after the pi pulse and before the readout pulse to allow for the 
qubit to relax back to the ground state. This should be long enough to allow 
for relaxation but short enough to avoid unnecessary waiting time.
"""
wait_after_pulse = 4000 * u.ns 

# Relaxation time from the metastable state to the ground state after during initialization
relaxation_time = 300 * u.ns
wait_for_initialization = 5 * relaxation_time

# MW parameters
mw_amp_NV = 0.2  # in units of volts
mw_len_NV = 100 * u.ns

x180_amp_NV = 0.25  # in units of volts
x180_len_NV = 90 // 4 * 4  # in units of ns

x90_amp_NV = x180_amp_NV  # in units of volts
# x90_amp_NV = 0.5
x90_len_NV = x180_len_NV / 2 // 4 * 4  # in units of ns

# RF parameters
rf_frequency = 10 * u.MHz
rf_amp = 0.1
rf_length = 1000

# Readout parameters
signal_threshold_1 = -500  # ADC units, to convert to volts divide by 4096 (12 bit ADC)
signal_threshold_2 = -500  # ADC units, to convert to volts divide by 4096 (12 bit ADC)

AOM_delay = (
    1015 // 4 * 4
)  # in clock cycles, to be adjusted to have the laser pulse start at the right time with respect to the detection window
Measurement_delay = (
    70 // 4 * 4
)  # in clock cycles, to be adjusted to have the detection window start at the right time with respect to the laser pulse
# Delays
detection_delay_1 = 80 + AOM_delay * u.ns
detection_delay_2 = 80 + AOM_delay * u.ns
laser_delay_1 = 0 * u.ns
laser_delay_2 = 0 * u.ns
mw_delay = 0 * u.ns
rf_delay = 0 * u.ns

trigger_delay = 57  # 57ns with QOP222 and above otherwise 87ns
trigger_buffer = 18  # 18ns with QOP222 and above otherwise 15ns

# initialization_len_2 = 9000 * u.ns
# long_meas_len_1 = 10000 * u.ns

wait_between_runs = 3000 * u.ns

con = "con1"

config = {
    "controllers": {
        con: {
            "analog_outputs": {
                1: {"offset": 0.0},
                2: {"offset": 0.0},
                3: {"offset": 0.0},
                4: {"offset": 0.0},
                5: {"offset": 0.0},
                6: {"offset": 0.0},
                7: {"offset": 0.0},
                8: {"offset": 0.0},
                9: {"offset": 0.0},
                10: {"offset": 0.0},
            },
            "digital_outputs": {
                1: {},
                2: {},
                3: {},
                4: {},
                5: {},
                6: {},
                7: {},
                8: {},
                9: {},
            },
            "analog_inputs": {
                1: {"offset": 0.0},
                2: {"offset": 0.0},
            },
        }
    },
    "elements": {
        "qe1": {
            "RF_inputs": {"port": (octave, 1)},
            "intermediate_frequency": NV_IF_freq,
            "operations": {
                "cw": "const",
                "cw_wo_trig": "const_wo_trig",
                "x180": "x180_pulse",
                "x90": "x90_pulse",
                "-x90": "-x90_pulse",
                "x270": "x270_pulse",
                "-y90": "-y90_pulse",
                "y90": "y90_pulse",
                "y180": "y180_pulse",
                "readout": "readout_pulse_with_IQ",
            },
            "digitalInputs": {
                "switch": {
                    "port": (con, 1),
                    "delay": trigger_delay,
                    "buffer": trigger_buffer,
                },
            },
            # "time_of_flight": 16,
            # "smearing": 0,
        },
        "photon_in_read": {
            "singleInput": {"port": (con, 1)}, # not used
            "outputs": {"out1": (con, 1)},
            "digitalInputs": {
                "digital_count_rate_out": {
                    "port": (con, 5),
                    "delay": detection_delay_1,
                    "buffer": 0,
                },
            },
            "operations": {
                "readout": "readout_pulse",
                "long_readout": "readout_pulse_long",
            },
            "time_of_flight": detection_delay_1,
            "timeTaggingParameters": {
                "signalThreshold": 0,
                "signalPolarity": "Above",
                "derivativeThreshold": 25,
                "derivativePolarity": "Above",
            },
        },
        "photon_in_read_2": {
            "singleInput": {"port": (con, 1)}, # not used
            "outputs": {"out1": (con, 2)},
            "digitalInputs": {
                "digital_count_rate_out": {
                    "port": (con, 4),
                    "delay": detection_delay_2,
                    "buffer": 0,
                },
            },
            "operations": {
                "readout": "readout_pulse",
                "long_readout": "readout_pulse_long",
            },
            "time_of_flight": detection_delay_2,
            "timeTaggingParameters": {
                "signalThreshold": 0,
                "signalPolarity": "Above",
                "derivativeThreshold": 25,
                "derivativePolarity": "Above",
            },
        },
        "aom_gate": {
            # AOM digital gate control element for qudi aom_controller module
            "digitalInputs": {
                "marker": {
                    "port": (con, 2),  # Digital marker 2 on front panel
                    "delay": laser_delay_2,
                    "buffer": 0,
                },
            },
            "operations": {
                "gate_on": "gate_on_pulse",
                "gate_on_long": "gate_on_long_pulse",
                "gate_off": "gate_off_pulse",
            },
        },
    },
    "octaves": {
        octave: {
            "RF_outputs": {
                1: {
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",  # can be external or internal. internal is the default
                    "output_mode": "triggered",  # can be: "always_on" / "always_off"/ "triggered" / "triggered_reversed". "always_off" is the default
                    "gain": 0,  # can be in the range [-20 : 0.5 : 20]dB
                },
            },
            "RF_inputs": {
                1: {
                    "RF_source": "RF_in",
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                },
                2: {
                    "RF_source": "RF_in",
                    "LO_frequency": NV_LO_freq,
                    "LO_source": "internal",
                },
            },
            "connectivity": con,
        }
    },
    "pulses": {
        "const": {
            "operation": "control",
            "length": 1000,
            "waveforms": {
                "I": "const_wf",
                "Q": "zero_wf",
            },
            "digital_marker": "ON",
        },
        "const_wo_trig": {
            "operation": "control",
            "length": 1000,
            "waveforms": {
                "I": "const_wf",
                "Q": "zero_wf",
            },
        },
        "readout_pulse": {
            "operation": "measurement",
            "length": 0.5 * u.us,
            "waveforms": {
                "single": "zero_wf",
            },
            "integration_weights": {
                "rect": "rectangular",
                "sin": "sine_weights",
                "cos": "cosine_weights",
            },
        },
        "readout_pulse_long": {
            # Longer time-tagging window used by the HBT (g2) measurement so that
            # correlations well beyond the NV lifetime can be resolved.
            "operation": "measurement",
            "length": long_meas_len_1,
            "waveforms": {
                "single": "zero_wf",
            },
            "integration_weights": {
                "rect": "rectangular",
                "sin": "sine_weights",
                "cos": "cosine_weights",
            },
        },
        "x180_pulse": {
            "operation": "control",
            "length": x180_len_NV,
            "waveforms": {"I": "x180_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "x90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "x90_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "-x90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "minus_x90_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "x270_pulse": {
            "operation": "control",
            "length": x90_len_NV * 3,
            "waveforms": {"I": "x270_wf", "Q": "zero_wf"},
            "digital_marker": "ON",
        },
        "-y90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "minus_x90_wf"},
            "digital_marker": "ON",
        },
        "y90_pulse": {
            "operation": "control",
            "length": x90_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "x90_wf"},
            "digital_marker": "ON",
        },
        "y180_pulse": {
            "operation": "control",
            "length": x180_len_NV,
            "waveforms": {"I": "zero_wf", "Q": "x180_wf"},
            "digital_marker": "ON",
        },
        "tick_pulse": {"operation": "control", "length": 40, "digital_marker": "ON"},
        "readout_pulse_with_IQ": {
            "operation": "measurement",
            "length": 20,  # ns
            "waveforms": {
                "I": "readout_wf",
                "Q": "zero_wf",
            },
            "integration_weights": {
                "cos": "cosine_weights",
                "sin": "sine_weights",
                "minus_sin": "minus_sine_weights",
                "rect": "rectangular",
            },
            "digital_marker": "OFF",
        },
        "gate_on_pulse": {
            # AOM gate ON pulse for qudi aom_controller module
            "operation": "control",
            "length": initialization_len_1,  
            "digital_marker": "ON",
        },
        "gate_on_long_pulse": {
            # AOM gate ON pulse for qudi aom_controller module
            "operation": "control",
            "length": 8000 * u.ns,  
            "digital_marker": "ON",
        },
        "gate_off_pulse": {
            # AOM gate OFF pulse for qudi aom_controller module
            "operation": "control",
            "length": 1000,  # 1us pulse
            "digital_marker": "OFF",
        },
    },
    "waveforms": {
        "zero_wf": {
            "type": "constant",
            "sample": 0.0,
        },
        "const_wf": {
            "type": "constant",
            "sample": 0.125,
        },
        "readout_wf": {
            "type": "constant",
            "sample": 0.125,
        },
        "x180_wf": {"type": "constant", "sample": x180_amp_NV},
        "x90_wf": {"type": "constant", "sample": x90_amp_NV},
        "minus_x90_wf": {"type": "constant", "sample": -x90_amp_NV},
        "x270_wf": {"type": "constant", "sample": x90_amp_NV},
    },
    "digital_waveforms": {
        "ON": {"samples": [(1, 0)]},
        "OFF": {"samples": [(0, 0)]},
    },
    "integration_weights": {
        "cosine_weights": {
            "cosine": [(1.0, 1000)],
            "sine": [(0.0, 1000)],
        },
        "sine_weights": {
            "cosine": [(0.0, 1000)],
            "sine": [(1.0, 1000)],
        },
        "minus_sine_weights": {
            "cosine": [(0.0, 1000)],
            "sine": [(-1.0, 1000)],
        },
        "rectangular": {"cosine": [1.0] * 1000, "sine": [1.0] * 1000},
    },
}
