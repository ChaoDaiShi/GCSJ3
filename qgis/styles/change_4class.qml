<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.15-Solothurn" styleCategories="AllStyleCategories" maxScale="0" minScale="1e+08" hasScaleBasedVisibilityFlag="0">
  <flags>
    <Identifiable>1</Identifiable>
    <Removable>1</Removable>
    <Searchable>1</Searchable>
    <Private>0</Private>
  </flags>
  <customproperties>
    <Option type="Map">
      <Option name="WMSBackgroundLayer" type="bool" value="false"/>
      <Option name="WMSPublishDataSourceUrl" type="bool" value="false"/>
      <Option name="embeddedWidgets/count" type="int" value="0"/>
      <Option name="identify/format" type="QString" value="Value"/>
    </Option>
  </customproperties>
  <pipe-data>
    <provider>
      <mode>gdal</mode>
    </provider>
    <rasterrenderer type="paletted" opacity="1" alphaBand="-1" band="1" nodataColor="0,0,0,0">
      <rasterTransparency>
        <singleValuePixelList>
          <pixelListEntry min="0" max="0" percentTransparent="100"/>
        </singleValuePixelList>
      </rasterTransparency>
      <colorPalette>
        <paletteEntry color="#000000" alpha="0" value="0" label="NoData"/>
        <paletteEntry color="#d95f02" alpha="255" value="1" label="持续建设"/>
        <paletteEntry color="#e41a1c" alpha="255" value="2" label="新增建设"/>
        <paletteEntry color="#377eb8" alpha="255" value="3" label="减少建设"/>
        <paletteEntry color="#b3b3b3" alpha="255" value="4" label="持续非建设"/>
      </colorPalette>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" colorizeStrength="100" grayscaleMode="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="0" colorizeOn="0"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe-data>
  <blendMode>0</blendMode>
</qgis>
