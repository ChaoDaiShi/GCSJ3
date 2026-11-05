<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.44.15-Solothurn" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0">
  <flags>
    <Identifiable>1</Identifiable>
    <Removable>1</Removable>
    <Searchable>1</Searchable>
    <Private>0</Private>
  </flags>
  <!-- 矢量分类渲染器：按 class_id (1~5) 分类显示对应颜色与名称 -->
  <renderer-v2 type="categorizedSymbol" attr="class_id" symbollevels="0" enableorderby="0" forceraster="0">
    <categories>
      <category value="1" symbol="0" label="1 建设用地" render="true"/>
      <category value="2" symbol="1" label="2 耕地" render="true"/>
      <category value="3" symbol="2" label="3 其他植被" render="true"/>
      <category value="4" symbol="3" label="4 水域" render="true"/>
      <category value="5" symbol="4" label="5 裸地" render="true"/>
    </categories>
    <symbols>
      <symbol type="fill" name="0" clip_to_extent="1" force_rhr="0" alpha="0.7">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="217,95,2,180"/>
            <Option name="outline_color" type="QString" value="217,95,2,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="1" clip_to_extent="1" force_rhr="0" alpha="0.7">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="230,200,79,180"/>
            <Option name="outline_color" type="QString" value="230,200,79,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="2" clip_to_extent="1" force_rhr="0" alpha="0.7">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="46,139,87,180"/>
            <Option name="outline_color" type="QString" value="46,139,87,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="3" clip_to_extent="1" force_rhr="0" alpha="0.7">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="55,126,184,180"/>
            <Option name="outline_color" type="QString" value="55,126,184,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="fill" name="4" clip_to_extent="1" force_rhr="0" alpha="0.7">
        <layer class="SimpleFill" enabled="1" locked="0" pass="0">
          <Option type="Map">
            <Option name="color" type="QString" value="182,156,125,180"/>
            <Option name="outline_color" type="QString" value="182,156,125,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <!-- 表单字段别名与编辑控件配置 -->
  <aliases>
    <alias field="sample_id" index="0" name="样本编号(唯一)"/>
    <alias field="group_id" index="1" name="地块组号(同组同类)"/>
    <alias field="year" index="2" name="年份"/>
    <alias field="class_id" index="3" name="地类编码(1-5)"/>
    <alias field="class_name" index="4" name="地类名称"/>
    <alias field="label_source" index="5" name="判读来源"/>
    <alias field="source_date" index="6" name="时相证据"/>
    <alias field="annotator" index="7" name="标注人"/>
    <alias field="split" index="8" name="划分状态(只读)"/>
  </aliases>
  <fieldConfiguration>
    <field name="class_id">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map"><Option name="1 建设用地" type="QString" value="1"/></Option>
              <Option type="Map"><Option name="2 耕地" type="QString" value="2"/></Option>
              <Option type="Map"><Option name="3 其他植被" type="QString" value="3"/></Option>
              <Option type="Map"><Option name="4 水域" type="QString" value="4"/></Option>
              <Option type="Map"><Option name="5 裸地" type="QString" value="5"/></Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field name="split">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option name="map" type="List">
              <Option type="Map"><Option name="未分配" type="QString" value="unassigned"/></Option>
              <Option type="Map"><Option name="训练集 (train)" type="QString" value="train"/></Option>
              <Option type="Map"><Option name="留出集 (holdout)" type="QString" value="holdout"/></Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
  </fieldConfiguration>
</qgis>
