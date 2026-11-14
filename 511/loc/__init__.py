"""Work package 5.1.1, stages after phase picking: association and hypocentre location.

velocity   1-D layered velocity model and P/S travel times (direct + head waves, flat earth)
geometry   lat/lon <-> local km conversion, station table loader
locate     grid-search + Nelder-Mead hypocentre location from P/S arrival times
associate  REAL-style back-projection associator that groups picks into events
synth      synthetic catalogue / picks for tests
"""
