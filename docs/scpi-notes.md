# SCPI notes for SDS824X HD

## What is stable

Common IEEE/SCPI commands are expected to work across most programmable instruments:

```text
*IDN?
:RUN
:STOP
:SINGLE
```

Basic channel/timebase/trigger commands are often similar across SIGLENT SDS families, but they still need to be verified against the SDS800X HD Programming Guide and the actual firmware version.

## Commands used in current scaffold

```text
*IDN?
:RUN
:STOP
:SINGLE
:TRIGger:FORCe
:CHANnel<n>:DISPlay ON
:CHANnel<n>:COUPling DC|AC|GND
:CHANnel<n>:SCALe <volts_per_div>
:CHANnel<n>:OFFSet <volts>
:TIMebase:SCALe <seconds_per_div>
:TIMebase:DELay <seconds>
:TRIGger:MODE EDGE
:TRIGger:EDGE:SOURce CHANnel<n>
:TRIGger:EDGE:SLOPe POS|NEG|EITHER
:TRIGger:EDGE:LEVel <volts>
:MEASure:VPP? CHANnel<n>
:MEASure:FREQuency? CHANnel<n>
:MEASure:PERiod? CHANnel<n>
```

## Commands to verify next

```text
# screenshot export
<screen image command>

# waveform export
:WAVeform:SOURce CHANnel<n>
:WAVeform:MODE <mode>
:WAVeform:FORMat BYTE|WORD|ASCii
:WAVeform:DATA?
:WAVeform:XINCrement?
:WAVeform:XORigin?
:WAVeform:YINCrement?
:WAVeform:YORigin?
:WAVeform:YREFerence?
```

The exact command names and returned binary block format must be confirmed from the official programming guide.

## Safety denylist

The scaffold blocks these classes of commands by default:

```text
*RST
:SYST:FACT
:SYSTem:FACTory
:MMEM:DEL
:MMEMory:DELete
:SYSTem:COMM:LAN
```

The denylist should grow after testing real command coverage.
