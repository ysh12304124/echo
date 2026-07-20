package com.echo.phone.ui.persons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.EchoRepository
import com.echo.phone.domain.PersonDetail
import com.echo.phone.domain.PersonSummary
import kotlinx.coroutines.launch

class PersonsViewModel(private val repo: EchoRepository) : ViewModel() {
    var persons by mutableStateOf<List<PersonSummary>>(emptyList())
    var loading by mutableStateOf(true)
    var selected by mutableStateOf<PersonDetail?>(null)
    var error by mutableStateOf<String?>(null)

    init { reload() }

    fun reload() {
        viewModelScope.launch {
            loading = true
            try { persons = repo.listPersons() } catch (e: Exception) { error = e.message }
            loading = false
        }
    }

    fun open(personId: String) {
        viewModelScope.launch {
            try { selected = repo.getPerson(personId) } catch (e: Exception) { error = e.message }
        }
    }

    fun close() { selected = null }

    fun rename(name: String) {
        val id = selected?.personId ?: return
        viewModelScope.launch {
            try { repo.renamePerson(id, name); reload(); selected = repo.getPerson(id) }
            catch (e: Exception) { error = e.message }
        }
    }

    fun merge(targetId: String) {
        val id = selected?.personId ?: return
        viewModelScope.launch {
            try { repo.mergePerson(id, targetId); close(); reload() }
            catch (e: Exception) { error = e.message }
        }
    }

    fun split(memoryIds: List<String>, newName: String) {
        val id = selected?.personId ?: return
        viewModelScope.launch {
            try { repo.splitPerson(id, memoryIds, newName); close(); reload() }
            catch (e: Exception) { error = e.message }
        }
    }

    fun delete() {
        val id = selected?.personId ?: return
        viewModelScope.launch {
            try { repo.deletePerson(id); close(); reload() }
            catch (e: Exception) { error = e.message }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: PersonsViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T = PersonsViewModel(app.repository) as T
        }
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("人物库") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回")
                    }
                },
            )
        },
    ) { padding ->
        if (vm.loading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (vm.persons.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("暂无人物")
            }
        } else {
            LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
                items(vm.persons) { person ->
                    Card(
                        Modifier.fillMaxWidth().padding(vertical = 4.dp)
                            .clickable { vm.open(person.personId) },
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(person.name, style = MaterialTheme.typography.titleSmall)
                            if (person.role.isNotEmpty()) Text(person.role, style = MaterialTheme.typography.bodySmall)
                            Text("${person.memoryCount} 段记忆", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }
        }
    }

    vm.selected?.let { detail ->
        PersonEditDialog(
            detail = detail,
            allPersons = vm.persons.filter { it.personId != detail.personId },
            onDismiss = { vm.close() },
            onRename = { vm.rename(it) },
            onMerge = { vm.merge(it) },
            onSplit = { ids, name -> vm.split(ids, name) },
            onDelete = { vm.delete() },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PersonEditDialog(
    detail: PersonDetail,
    allPersons: List<PersonSummary>,
    onDismiss: () -> Unit,
    onRename: (String) -> Unit,
    onMerge: (String) -> Unit,
    onSplit: (List<String>, String) -> Unit,
    onDelete: () -> Unit,
) {
    var name by remember(detail.personId) { mutableStateOf(detail.name) }
    var mergeExpanded by remember { mutableStateOf(false) }
    val splitSelection = remember(detail.personId) { mutableStateListOf<String>() }
    var splitName by remember(detail.personId) { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑人物") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("姓名") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(onClick = { onRename(name) }, modifier = Modifier.padding(top = 4.dp)) {
                    Text("重命名")
                }

                Spacer(Modifier.height(12.dp))
                Text("合并到其他人物", style = MaterialTheme.typography.labelLarge)
                ExposedDropdownMenuBox(expanded = mergeExpanded, onExpandedChange = { mergeExpanded = it }) {
                    OutlinedTextField(
                        value = "选择目标人物",
                        onValueChange = {},
                        readOnly = true,
                        modifier = Modifier.fillMaxWidth().menuAnchor(),
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = mergeExpanded) },
                    )
                    ExposedDropdownMenu(expanded = mergeExpanded, onDismissRequest = { mergeExpanded = false }) {
                        allPersons.forEach { p ->
                            DropdownMenuItem(text = { Text(p.name) }, onClick = {
                                mergeExpanded = false
                                onMerge(p.personId)
                            })
                        }
                    }
                }

                if (detail.relatedMemories.isNotEmpty()) {
                    Spacer(Modifier.height(12.dp))
                    Text("拆分（把选中记忆分给新人物）", style = MaterialTheme.typography.labelLarge)
                    detail.relatedMemories.forEach { mid ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = splitSelection.contains(mid),
                                onCheckedChange = {
                                    if (it) splitSelection.add(mid) else splitSelection.remove(mid)
                                },
                            )
                            Text(mid.take(8), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    OutlinedTextField(
                        value = splitName,
                        onValueChange = { splitName = it },
                        label = { Text("新人物姓名") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = { onSplit(splitSelection.toList(), splitName) },
                        enabled = splitSelection.isNotEmpty(),
                        modifier = Modifier.padding(top = 4.dp),
                    ) { Text("拆分") }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("完成") }
        },
        dismissButton = {
            TextButton(onClick = onDelete) { Text("删除人物", color = MaterialTheme.colorScheme.error) }
        },
    )
}
