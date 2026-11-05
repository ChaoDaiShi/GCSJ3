<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.15-Solothurn" styleCategories="AllStyleCategories" simplifyAlgorithm="0" simplifyDrawingHints="1" simplifyDrawingTol="1" simplifyLocal="1" simplifyMaxScale="1" hasScaleBasedVisibilityFlag="0">
  <flags>
    <Identifiable>1</Identifiable>
    <Removable>1</Removable>
    <Searchable>1</Searchable>
    <Private>0</Private>
  </flags>
  <renderer-v2 type="graduatedSymbol" attr="annual_intensity_pct" symbollevels="0" enableorderby="0" forceraster="0" graduatedMethod="GraduatedColor">
    <ranges>
      <range lower="0.000000" upper="0.200000" symbol="0" label="0.00% - 0.20% (低速)"/>
      <range lower="0.200000" upper="0.500000" symbol="1" label="0.20% - 0.50% (中低速)"/>
      <range lower="0.500000" upper="1.000000" symbol="2" label="0.50% - 1.00% (中速)"/>
      <range lower="1.000000" upper="2.000000" symbol="3" label="1.00% - 2.00% (高速)"/>
      <range lower="2.000000" upper="10.000000" symbol="4" label="> 2.00% (极高速)"/>
    </ranges>
    <symbols>
      <symbol type="fill" name="0" clip_to_extent="1" force_rhr="0" alpha="0.85">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="254,237,222,255"/>
            <Option name="outline_color" type="QString" value="80,80,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" clip_to_extent="1" force_rhr="0" alpha="0.85">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="253,190,133,255"/>
            <Option name="outline_color" type="QString" value="80,80,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" clip_to_extent="1" force_rhr="0" alpha="0.85">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="253,141,60,255"/>
            <Option name="outline_color" type="QString" value="80,80,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" clip_to_extent="1" force_rhr="0" alpha="0.85">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="230,85,13,255"/>
            <Option name="outline_color" type="QString" value="80,80,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="4" clip_to_extent="1" force_rhr="0" alpha="0.85">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="166,54,3,255"/>
            <Option name="outline_color" type="QString" value="80,80,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.3"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="style" type="QString" value="solid"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
</qgis>
