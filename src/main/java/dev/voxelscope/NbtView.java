package dev.voxelscope;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.Collections;
import net.minecraft.nbt.CollectionTag;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.NumericTag;
import net.minecraft.nbt.StringTag;
import net.minecraft.nbt.Tag;

/** Shallow schema or ONE selected scalar. Never serializes a whole compound/list to the API. */
final class NbtView {
    static JsonObject inspect(Tag root, String path, int offset, int limit) {
        if (path.length() > 512 || (!path.isEmpty() && !path.startsWith("/"))) {
            throw new IllegalArgumentException("invalid_data_path");
        }
        Tag selected = root;
        if (!path.isEmpty()) {
            String[] parts = path.substring(1).split("/", -1);
            if (parts.length > 16) throw new IllegalArgumentException("data_path_too_deep");
            for (String encoded : parts) {
                if (encoded.matches(".*~(?![01]).*")) throw new IllegalArgumentException("invalid_data_path_escape");
                String key = encoded.replace("~1", "/").replace("~0", "~");
                if (selected instanceof CompoundTag compound) {
                    selected = compound.get(key);
                } else if (selected instanceof CollectionTag<?> array) {
                    int index;
                    try { index = Integer.parseInt(key); }
                    catch (NumberFormatException bad) { throw new IllegalArgumentException("invalid_data_index"); }
                    selected = index >= 0 && index < array.size() ? array.get(index) : null;
                } else {
                    selected = null;
                }
                if (selected == null) throw new IllegalArgumentException("data_path_not_found");
            }
        }
        JsonObject result = describe(selected, path);
        if (selected instanceof NumericTag numeric) {
            Number number = numeric.getAsNumber();
            if (Double.isFinite(number.doubleValue())) result.addProperty("value", number);
            else result.addProperty("non_finite", true);
        } else if (selected instanceof StringTag string) {
            String value = string.getAsString();
            result.addProperty("value", value.substring(0, Math.min(256, value.length())));
            result.addProperty("value_truncated", value.length() > 256);
        } else {
            JsonArray children = new JsonArray();
            int size;
            if (selected instanceof CompoundTag compound) {
                size = compound.size();
                if (size > 4096) throw new IllegalArgumentException("too_many_data_keys_select_explicit_path");
                var keys = new ArrayList<>(compound.getAllKeys());
                Collections.sort(keys);
                for (int i = offset; i < Math.min(size, offset + limit); i++) {
                    String key = keys.get(i);
                    if (key.length() > 256) continue;
                    String childPath = path + "/" + key.replace("~", "~0").replace("/", "~1");
                    children.add(describe(compound.get(key), childPath));
                }
            } else if (selected instanceof CollectionTag<?> collection) {
                size = collection.size();
                for (int i = offset; i < Math.min(size, offset + limit); i++) {
                    children.add(describe(collection.get(i), path + "/" + i));
                }
            } else {
                size = 0;
            }
            result.add("children", children);
            result.addProperty("size", size);
            result.addProperty("offset", offset);
            result.addProperty("truncated", offset + limit < size);
            if (offset + limit < size) result.addProperty("next_offset", offset + limit);
        }
        result.addProperty("unit", "unknown");
        result.addProperty("source", "saved_data_snapshot");
        result.addProperty("note", "Saved fields may omit live multiblock statistics. Numeric types do not establish units or meaning.");
        return result;
    }

    private static JsonObject describe(Tag tag, String path) {
        JsonObject result = new JsonObject();
        result.addProperty("path", path);
        result.addProperty("type", tag.getType().getName());
        result.addProperty("numeric", tag instanceof NumericTag);
        return result;
    }
}
